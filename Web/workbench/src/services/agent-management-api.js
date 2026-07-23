export const AgentManagementOperations = Object.freeze({
  create: 'create',
  fineTune: 'fine_tune',
  upgrade: 'upgrade',
  promote: 'promote',
  publish: 'publish',
  deactivate: 'deactivate',
  restore: 'restore',
})

/**
 * L4 application boundary for Agent and Skill commands. Replace this acknowledgement with
 * a POST to the same endpoint when the L2 orchestration service is available.
 */
export const agentManagementApplicationApi = {
  endpoint: '/api/application/capability-management/commands',

  acceptCommand(command) {
    return {
      accepted: true,
      traceId: `L4-AG-${Date.now().toString().slice(-6)}`,
      command,
    }
  },
}
