(() => {
  async function move(id, status) {
    const response = await fetch(`/tasks/${id}/status`, {method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify({status})});
    const result=await response.json();
    if (!response.ok) throw new Error(result.error || 'The task could not be moved.');
    const card=document.querySelector(`[data-task-id="${id}"].task-card`);
    document.querySelector(`[data-status="${status}"] .kanban-cards`).append(card);
    card.querySelector('select').value=status;
    document.querySelectorAll('.kanban-column').forEach(col=>col.querySelector('h2 span').textContent=col.querySelectorAll('.task-card').length);
  }
  document.querySelectorAll('.task-status-select').forEach(select=>select.addEventListener('change',async()=>{const previous=select.closest('.kanban-column').dataset.status;select.disabled=true;try{await move(select.dataset.taskId,select.value);}catch(error){select.value=previous;alert(error.message);}finally{select.disabled=false;}}));
  document.querySelectorAll('.task-card').forEach(card=>card.addEventListener('dragstart',event=>event.dataTransfer.setData('text/plain',card.dataset.taskId)));
  document.querySelectorAll('.kanban-column').forEach(column=>{column.addEventListener('dragover',event=>event.preventDefault());column.addEventListener('drop',async event=>{event.preventDefault();const id=event.dataTransfer.getData('text/plain');if(!/^\d+$/.test(id))return;try{await move(id,column.dataset.status);}catch(error){alert(error.message);}});});
})();
