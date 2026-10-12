import pytest
from app.extensions import db
from app.models import (
    Client,
    Lead,
    Inquiry,
    Task,
    TaskDependency,
    ScopeItem,
    Approval,
    ProjectStage,
    Requirement,
)
from app.services.lifecycle_service import create_project, complete_stage


def make_project():
    client = Client(name="Fictional Owner", business_name="Fictional Agency")
    db.session.add(client)
    db.session.flush()
    project = create_project(client, "Fictional website")
    db.session.commit()
    return project


def test_crm_validation_and_archive(auth_client):
    assert (
        auth_client.post(
            "/clients/new", data={"name": "", "business_name": "Example"}
        ).status_code
        == 400
    )
    assert (
        auth_client.post(
            "/clients/new",
            data={"name": "Owner", "business_name": "Example", "email": "invalid"},
        ).status_code
        == 400
    )
    assert Client.query.count() == 0
    response = auth_client.post(
        "/clients/new",
        data={
            "name": "Owner",
            "business_name": "Example",
            "email": "owner@example.com",
        },
    )
    assert response.status_code == 302
    client = Client.query.one()
    assert (
        auth_client.post(
            f"/clients/{client.id}/edit",
            data={"name": "Updated", "business_name": "Example"},
        ).status_code
        == 302
    )
    assert client.name == "Updated"
    project = create_project(client, "Website")
    db.session.commit()
    assert (
        auth_client.post(
            f"/clients/{client.id}/archive", data={"confirmed": "yes"}
        ).status_code
        == 400
    )
    assert (
        auth_client.post(
            f"/projects/{project.id}/status", data={"status": "paused"}
        ).status_code
        == 302
    )
    assert (
        auth_client.post(
            f"/clients/{client.id}/archive", data={"confirmed": "yes"}
        ).status_code
        == 302
    )
    assert client.status == "archived"
    assert (
        auth_client.post(
            "/projects/new", data={"client_id": client.id, "title": "Blocked"}
        ).status_code
        == 400
    )


def test_lead_conversion_requires_qualification(auth_client):
    auth_client.post(
        "/leads/new",
        data={"name": "Owner", "business_name": "Prospect", "status": "new"},
    )
    lead = Lead.query.one()
    assert (
        auth_client.post(
            f"/leads/{lead.id}/convert", data={"confirmed": "yes"}
        ).status_code
        == 400
    )
    assert Client.query.count() == 0


@pytest.mark.parametrize("budget", ["not-money", "NaN", "Infinity", "-1"])
def test_invalid_inquiry_budget_is_rejected(auth_client, budget):
    project = make_project()
    response = auth_client.post(
        "/inquiries/new",
        data={
            "client_id": project.client_id,
            "website_type": "Business",
            "budget": budget,
        },
    )
    assert response.status_code == 400
    assert Inquiry.query.count() == 0


def test_tasks_dependencies_and_cycle_rejection(auth_client):
    project = make_project()
    one = Task(project_id=project.id, title="First", status="ready")
    two = Task(project_id=project.id, title="Second", status="ready")
    db.session.add_all([one, two])
    db.session.commit()
    assert (
        auth_client.post(
            f"/tasks/{two.id}/dependencies", data={"depends_on_id": one.id}
        ).status_code
        == 302
    )
    assert (
        auth_client.post(
            f"/tasks/{one.id}/dependencies", data={"depends_on_id": two.id}
        ).status_code
        == 400
    )
    assert (
        auth_client.post(
            f"/tasks/{two.id}/status", json={"status": "completed"}
        ).status_code
        == 400
    )
    assert (
        auth_client.post(
            f"/tasks/{one.id}/status", json={"status": "completed"}
        ).status_code
        == 200
    )
    assert (
        auth_client.post(
            f"/tasks/{two.id}/status", json={"status": "completed"}
        ).status_code
        == 200
    )
    assert TaskDependency.query.count() == 1


def test_stage_is_not_completed_by_checklist_alone(auth_client, admin):
    project = make_project()
    stage = ProjectStage.query.filter_by(project_id=project.id, number=1).one()
    stage.data = {"qualification": "Reviewed", "service": "Business website"}
    for item in Requirement.query.filter_by(project_id=project.id, stage_number=1):
        item.completed = True
    db.session.commit()
    with pytest.raises(ValueError, match="explicit stage approval"):
        complete_stage(project, 1, admin.id)
    db.session.add(
        Approval(
            project_id=project.id,
            stage_number=1,
            kind="stage",
            decision="approved",
            person="Owner",
            evidence="Written qualification review",
            actor_id=admin.id,
        )
    )
    db.session.commit()
    complete_stage(project, 1, admin.id)
    db.session.commit()
    assert project.current_stage == 2
    before = Task.query.count()
    complete_stage(project, 1, admin.id)
    db.session.commit()
    assert Task.query.count() == before


def test_required_scope_criteria_and_missing_objects(auth_client):
    project = make_project()
    response = auth_client.post(
        f"/projects/{project.id}/scope",
        data={"name": "Homepage", "hours": "2", "acceptance_criteria": ""},
    )
    assert response.status_code == 400
    assert ScopeItem.query.count() == 0
    for path in ["/clients/99999", "/projects/99999", "/leads/99999", "/tasks/99999"]:
        assert auth_client.get(path).status_code == 404
