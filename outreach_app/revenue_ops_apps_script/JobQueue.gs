const JobQueue = (() => {
  function enqueueJob(jobType, entityType, entityId, payloadHash, priority, requestedBy) {
    const lock = LockService.getScriptLock();
    lock.waitLock(30000);
    try {
      const existing = Repository.getLatest('AI_Jobs', (job) => {
        const status = String(job.status || '');
        return job.job_type === jobType &&
          String(job.entity_type) === String(entityType) &&
          String(job.entity_id) === String(entityId) &&
          String(job.payload_hash) === String(payloadHash) &&
          ['pending', 'leased', 'retry'].indexOf(status) !== -1;
      }, ['updated_at', 'created_at']);
      if (existing) {
        return existing;
      }

      return Repository.append('AI_Jobs', [{
        job_id: Utils.uuid('job'),
        created_at: Utils.nowIso(),
        updated_at: Utils.nowIso(),
        job_type: jobType,
        entity_type: entityType,
        entity_id: entityId,
        payload_hash: payloadHash,
        priority: Utils.asInt(priority, 50),
        status: 'pending',
        attempt_count: 0,
        lease_owner: '',
        leased_until: '',
        next_retry_at: '',
        requested_by: requestedBy || '',
        error_message: '',
      }])[0];
    } finally {
      lock.releaseLock();
    }
  }

  function processPendingJobs(maxJobs) {
    const batchSize = maxJobs || ConfigService.getNumber('WORKER_BATCH_SIZE', 8);
    const workerId = Utils.uuid('worker');
    const claimed = claimJobs_(workerId, batchSize);
    let processed = 0;

    claimed.forEach((job) => {
      try {
        const result = JobProcessor.process(job);
        Repository.updateRow('AI_Jobs', job.__rowNumber, {
          updated_at: Utils.nowIso(),
          status: 'completed',
          leased_until: '',
          lease_owner: '',
          error_message: '',
        });
        processed += 1;
        LogService.info('JobQueue.processPendingJobs', {
          jobId: job.job_id,
          entityType: job.entity_type,
          entityId: job.entity_id,
          message: 'Completed job ' + job.job_type + ' -> output ' + result.outputId,
        });
      } catch (error) {
        handleJobError_(job, error);
      }
    });

    return processed;
  }

  function claimJobs_(workerId, maxJobs) {
    const lock = LockService.getScriptLock();
    lock.waitLock(30000);
    try {
      const now = new Date();
      const leaseMinutes = ConfigService.getNumber('JOB_LEASE_MINUTES', 10);
      const claimable = Repository.getAll('AI_Jobs').filter((job) => {
        const status = String(job.status || '');
        if (status === 'completed' || status === 'dead_letter' || status === 'failed') {
          return false;
        }
        if (status === 'leased') {
          const leasedUntil = Utils.toDate(job.leased_until);
          return !leasedUntil || leasedUntil.getTime() <= now.getTime();
        }
        if (status === 'retry') {
          const nextRetryAt = Utils.toDate(job.next_retry_at);
          return !nextRetryAt || nextRetryAt.getTime() <= now.getTime();
        }
        return status === 'pending' || !status;
      }).sort((a, b) => {
        const priorityDiff = Utils.asInt(b.priority, 0) - Utils.asInt(a.priority, 0);
        if (priorityDiff !== 0) {
          return priorityDiff;
        }
        return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
      }).slice(0, maxJobs);

      claimable.forEach((job) => {
        Repository.updateRow('AI_Jobs', job.__rowNumber, {
          updated_at: Utils.nowIso(),
          status: 'leased',
          attempt_count: Utils.asInt(job.attempt_count, 0) + 1,
          lease_owner: workerId,
          leased_until: Utils.addMinutes(Utils.nowIso(), leaseMinutes),
          next_retry_at: '',
          error_message: '',
        });
      });

      return claimable.map((job) => Repository.getRecordByRow('AI_Jobs', job.__rowNumber));
    } finally {
      lock.releaseLock();
    }
  }

  function handleJobError_(job, error) {
    const maxAttempts = ConfigService.getNumber('MAX_JOB_ATTEMPTS', 5);
    const attempts = Utils.asInt(job.attempt_count, 0);
    const patch = {
      updated_at: Utils.nowIso(),
      leased_until: '',
      lease_owner: '',
      error_message: Utils.truncate(Utils.stringifyError(error), 4000),
    };

    if (attempts >= maxAttempts) {
      patch.status = 'dead_letter';
      Repository.updateRow('AI_Jobs', job.__rowNumber, patch);
      LogService.error('JobQueue.handleJobError', error, {
        jobId: job.job_id,
        entityType: job.entity_type,
        entityId: job.entity_id,
        message: 'Job moved to dead letter.',
      });
      return;
    }

    const backoffMinutes = Math.min(Math.pow(2, Math.max(0, attempts - 1)), 60);
    patch.status = 'retry';
    patch.next_retry_at = Utils.addHours(Utils.nowIso(), backoffMinutes / 60);
    Repository.updateRow('AI_Jobs', job.__rowNumber, patch);
    LogService.error('JobQueue.handleJobError', error, {
      jobId: job.job_id,
      entityType: job.entity_type,
      entityId: job.entity_id,
      message: 'Job scheduled for retry.',
    });
  }

  function getQueueSummary() {
    const jobs = Repository.getAll('AI_Jobs');
    const summary = {
      pending: 0,
      leased: 0,
      retry: 0,
      completed: 0,
      dead_letter: 0,
    };
    jobs.forEach((job) => {
      const key = String(job.status || 'pending');
      if (!Object.prototype.hasOwnProperty.call(summary, key)) {
        summary[key] = 0;
      }
      summary[key] += 1;
    });
    return summary;
  }

  return {
    enqueueJob,
    getQueueSummary,
    processPendingJobs,
  };
})();
