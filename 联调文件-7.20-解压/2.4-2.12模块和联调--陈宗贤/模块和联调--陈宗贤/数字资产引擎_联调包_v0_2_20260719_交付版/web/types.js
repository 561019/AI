/**
 * @typedef {"digital_employee"|"skill"|"knowledge_base"|"material"} AssetType
 * @typedef {"draft"|"pending"|"published"|"disabled"|"deleted"} AssetStatus
 * @typedef {"personal"|"department"|"company"|"group"} AssetScope
 * @typedef {"synced"|"unsynced"|"not_required"|"failed"} SyncStatus
 * @typedef {"healthy"|"warning"|"error"} HealthStatus
 * @typedef {"untested"|"passed"|"failed"} TestStatus
 *
 * @typedef {Object} Asset
 * @property {string} id
 * @property {string} name
 * @property {AssetType} type
 * @property {string} department
 * @property {string} owner
 * @property {string} maintainer
 * @property {AssetScope} scope
 * @property {AssetStatus} status
 * @property {string} version
 * @property {SyncStatus} syncStatus
 * @property {HealthStatus} healthStatus
 * @property {number} metadataCompleteness
 * @property {string} description
 * @property {string} businessContext
 * @property {string[]} relatedKnowledgeBaseIds
 * @property {string[]} relatedSkillIds
 * @property {string[]} relatedMaterialIds
 * @property {string} toolRef
 * @property {string} createdAt
 * @property {string} updatedAt
 *
 * @typedef {Object} VersionRecord
 * @typedef {Object} PublishRecord
 * @typedef {Object} ApprovalRecord
 * @typedef {Object} PermissionCheckRecord
 * @typedef {Object} SyncRecord
 * @typedef {Object} KnowledgeIngestionRecord
 * @typedef {Object} HealthCheckRecord
 * @typedef {Object} OperationLog
 * @typedef {Object} TestRecord
 */

window.DA_TYPE_DOC_READY = true;
