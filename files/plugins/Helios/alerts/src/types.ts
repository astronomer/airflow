export type AlertSeverity = (typeof AlertSeverity)[keyof typeof AlertSeverity];

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const AlertSeverity = {
  INFO: 'INFO',
  WARNING: 'WARNING',
  CRITICAL: 'CRITICAL',
} as const;

export type AlertType = (typeof AlertType)[keyof typeof AlertType];

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const AlertType = {
  DAG_SUCCESS: 'DAG_SUCCESS',
  DAG_FAILURE: 'DAG_FAILURE',
  DAG_DURATION: 'DAG_DURATION',
  TASK_DURATION: 'TASK_DURATION',
  ABSOLUTE_TIME: 'ABSOLUTE_TIME',
  TASK_FAILURE: 'TASK_FAILURE',
  DATA_PRODUCT_SLA: 'DATA_PRODUCT_SLA',
  DATA_PRODUCT_PROACTIVE_FAILURE: 'DATA_PRODUCT_PROACTIVE_FAILURE',
  DATA_PRODUCT_PROACTIVE_SLA: 'DATA_PRODUCT_PROACTIVE_SLA',
  AIRFLOW_DB_STORAGE_UNUSUALLY_HIGH: 'AIRFLOW_DB_STORAGE_UNUSUALLY_HIGH',
  DEPRECATED_RUNTIME_VERSION: 'DEPRECATED_RUNTIME_VERSION',
  JOB_SCHEDULING_DISABLED: 'JOB_SCHEDULING_DISABLED',
  WORKER_QUEUE_AT_CAPACITY: 'WORKER_QUEUE_AT_CAPACITY',
} as const;


type Alert = {
  alertNotificationsFailedCount?: number;
  alertNotificationsSentCount?: number;
  createdAt: string;
  createdBy: Record<string, any>;
  dataProductId?: string;
  dataProductName?: string;
  definition?: unknown;
  deploymentAirflowVersion?: string;
  deploymentId?: string;
  deploymentName?: string;
  deploymentReleaseName?: string;
  entityId: string;
  entityName?: string;
  entityType: string;
  id: string;
  insightId?: string;
  name: string;
  notificationChannels?: Record<string, any>[];
  organizationId: string;
  organizationName?: string;
  rules?: Record<string, any>;
  severity: AlertSeverity;
  slaId?: string;
  slaName?: string;
  slaType?: string;
  type: AlertType;
  updatedAt: string;
  updatedBy: Record<string, any>;
  workspaceId?: string;
  workspaceName?: string;
};


export type AlertsPaginated = {
  alerts: Alert[];
  limit: number;
  offset: number;
  periodAlertNotificationsTriggerCount?: number;
  totalCount: number;
};
