const TaskService = (() => {
  function ensureOpenTask(task) {
    const record = Object.assign({
      task_id: Utils.uuid('task'),
      created_at: Utils.nowIso(),
      entity_type: '',
      entity_id: '',
      owner: '',
      task_type: '',
      due_at: Utils.nowIso(),
      priority: 'medium',
      status: 'open',
      auto_generated: true,
      notes: '',
    }, task || {});

    const existing = Repository.getLatest('Tasks', (item) => {
      return item.status === 'open' &&
        String(item.entity_type) === String(record.entity_type) &&
        String(item.entity_id) === String(record.entity_id) &&
        String(item.task_type) === String(record.task_type) &&
        String(item.owner || '') === String(record.owner || '');
    }, ['due_at', 'created_at']);

    if (existing) {
      return Repository.updateRow('Tasks', existing.__rowNumber, {
        due_at: record.due_at || existing.due_at,
        priority: record.priority || existing.priority,
        notes: record.notes || existing.notes,
        auto_generated: record.auto_generated,
      });
    }

    return Repository.append('Tasks', [record])[0];
  }

  function getOpenTasks(entityType, entityId) {
    return Repository.filter('Tasks', (task) => {
      return task.status === 'open' &&
        String(task.entity_type) === String(entityType) &&
        String(task.entity_id) === String(entityId);
    });
  }

  function closeTasks(entityType, entityId, taskType) {
    const tasks = Repository.filter('Tasks', (task) => {
      return task.status === 'open' &&
        String(task.entity_type) === String(entityType) &&
        String(task.entity_id) === String(entityId) &&
        (!taskType || String(task.task_type) === String(taskType));
    });
    tasks.forEach((task) => {
      Repository.updateRow('Tasks', task.__rowNumber, { status: 'done' });
    });
    return tasks.length;
  }

  return {
    closeTasks,
    ensureOpenTask,
    getOpenTasks,
  };
})();
