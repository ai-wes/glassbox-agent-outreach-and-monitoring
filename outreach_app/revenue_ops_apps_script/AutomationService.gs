const AutomationService = (() => {
  function getStatus() {
    const paused = ConfigService.getBoolean('AUTOMATION_PAUSED', false);
    return {
      paused: paused,
      state: paused ? 'paused' : 'running',
      updatedAt: Utils.nowIso(),
    };
  }

  function isPaused() {
    return ConfigService.getBoolean('AUTOMATION_PAUSED', false);
  }

  function pause() {
    ConfigService.setVisibleConfig(
      'AUTOMATION_PAUSED',
      'true',
      'If true, scheduled queue processing, hourly maintenance, and daily digests are paused.'
    );
    LogService.warn('AutomationService.pause', {
      message: 'Scheduled automation paused.',
      entityType: 'automation',
      entityId: 'global',
    });
    return getStatus();
  }

  function resume() {
    ConfigService.setVisibleConfig(
      'AUTOMATION_PAUSED',
      'false',
      'If true, scheduled queue processing, hourly maintenance, and daily digests are paused.'
    );
    LogService.info('AutomationService.resume', {
      message: 'Scheduled automation resumed.',
      entityType: 'automation',
      entityId: 'global',
    });
    return getStatus();
  }

  function shouldRun(triggerName) {
    if (!isPaused()) {
      return true;
    }
    LogService.warn('AutomationService.shouldRun', {
      message: 'Skipped scheduled execution because automation is paused. trigger=' + triggerName,
      entityType: 'automation',
      entityId: triggerName || 'unknown',
    });
    return false;
  }

  return {
    getStatus,
    isPaused,
    pause,
    resume,
    shouldRun,
  };
})();
