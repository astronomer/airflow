export const airflowVariablesData = {
  environmentObjects: [
    {
      id: "cm2l1ro8z006101q35w36mh6g",
      scope: "WORKSPACE",
      scopeEntityId: "clx9g3xak000w01ksr29jl6f2",
      objectType: "VARIABLE",
      objectKey: "environment",
      variable: {
        value: "production",
        description: "Current deployment environment",
        isSecret: false,
      },
      links: [
        {
          scope: "DEPLOYMENT",
          scopeEntityId: "clyz2mshy00e501p1vchz64yx",
          variableOverrides: {},
        },
      ],
      createdAt: "2024-10-22T22:58:55.237Z",
      updatedAt: "2024-10-22T22:59:17.321Z",
      createdBy: {
        id: "cl6zt14k7480291jzcdy0n8xzi",
        subjectType: "USER",
        username: "ryan@astronomer.io",
        fullName: "Ryan Hamilton",
        avatarUrl:
          "https://s.gravatar.com/avatar/6dea52b82fbf78cb2eefda489027ef79?s=480&r=pg&d=https%3A%2F%2Fcdn.auth0.com%2Favatars%2Frh.png",
      },
      updatedBy: {
        id: "cl6zt14k7480291jzcdy0n8xzi",
        subjectType: "USER",
        username: "ryan@astronomer.io",
        fullName: "Ryan Hamilton",
        avatarUrl:
          "https://s.gravatar.com/avatar/6dea52b82fbf78cb2eefda489027ef79?s=480&r=pg&d=https%3A%2F%2Fcdn.auth0.com%2Favatars%2Frh.png",
      },
    },
    {
      id: "cmdz3488k02wa01l5ckjq8eqx",
      scope: "WORKSPACE",
      scopeEntityId: "clx9g3xak000w01ksr29jl6f2",
      objectType: "VARIABLE",
      objectKey: "s3_data_bucket",
      variable: {
        value: "s3://my-company-airflow-data",
        description: "Primary S3 bucket for data processing",
        isSecret: false,
      },
      links: [
        {
          scope: "DEPLOYMENT",
          scopeEntityId: "clyz2mshy00e501p1vchz64yx",
          variableOverrides: {
            value: "s3://my-company-dev-data",
          },
        },
      ],
      createdAt: "2025-08-05T22:02:12.79Z",
      updatedAt: "2025-08-05T22:02:17.555Z",
      createdBy: {
        id: "cm8nliy1v020n01mirihbvj5y",
        subjectType: "USER",
        username: "william.shi@astronomer.io",
        fullName: "William Shi",
        avatarUrl:
          "https://lh3.googleusercontent.com/a/ACg8ocJ2NpziJkxWB7meKW490TElsJLPn5SnqwQX3XmqLOZ4JjUdsg=s96-c",
      },
      updatedBy: {
        id: "cm8nliy1v020n01mirihbvj5y",
        subjectType: "USER",
        username: "william.shi@astronomer.io",
        fullName: "William Shi",
        avatarUrl:
          "https://lh3.googleusercontent.com/a/ACg8ocJ2NpziJkxWB7meKW490TElsJLPn5SnqwQX3XmqLOZ4JjUdsg=s96-c",
      },
    },
    {
      id: "cmbjoijki0lmk01psxjcuwla5",
      scope: "WORKSPACE",
      scopeEntityId: "clx9g3xak000w01ksr29jl6f2",
      objectType: "VARIABLE",
      objectKey: "slack_webhook_url",
      variable: {
        value: "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX",
        description: "Slack webhook for DAG failure notifications",
        isSecret: true,
      },
      createdAt: "2025-06-05T17:57:29.108Z",
      updatedAt: "2025-08-06T03:28:51.177Z",
      createdBy: {
        id: "cl7qqe4tf264442d28fttoe7g8",
        subjectType: "USER",
        username: "vandy.liu@astronomer.io",
        fullName: "Vandy Liu",
        avatarUrl:
          "https://s.gravatar.com/avatar/ea0265af113c7429c02cf1de98f03552?s=480&r=pg&d=https%3A%2F%2Fcdn.auth0.com%2Favatars%2Fvl.png",
      },
      updatedBy: {
        id: "ckx6ogzn059721g078uxv3a7k",
        subjectType: "USER",
        username: "frank.ye@astronomer.io",
        fullName: "Frank Ye",
        avatarUrl:
          "https://s.gravatar.com/avatar/4aeef6ff7b072193b1d2d9fdf9c2be1f?s=480&r=pg&d=https%3A%2F%2Fcdn.auth0.com%2Favatars%2Ffy.png",
      },
    },
    {
      id: "cmbh3kj7u005u01lc41gcf14a",
      scope: "WORKSPACE",
      scopeEntityId: "clx9g3xak000w01ksr29jl6f2",
      objectType: "VARIABLE",
      objectKey: "max_active_runs",
      variable: {
        value: "16",
        description: "Maximum number of active DAG runs",
        isSecret: false,
      },
      links: [
        {
          scope: "DEPLOYMENT",
          scopeEntityId: "cmbh39k15000j01mk2092ez9f",
          variableOverrides: {
            value: "8",
          },
        },
      ],
      createdAt: "2025-06-03T22:35:37.676Z",
      updatedAt: "2025-08-06T03:29:15.046Z",
      createdBy: {
        id: "cl7qqe4tf264442d28fttoe7g8",
        subjectType: "USER",
        username: "vandy.liu@astronomer.io",
        fullName: "Vandy Liu",
        avatarUrl:
          "https://s.gravatar.com/avatar/ea0265af113c7429c02cf1de98f03552?s=480&r=pg&d=https%3A%2F%2Fcdn.auth0.com%2Favatars%2Fvl.png",
      },
      updatedBy: {
        id: "ckx6ogzn059721g078uxv3a7k",
        subjectType: "USER",
        username: "frank.ye@astronomer.io",
        fullName: "Frank Ye",
        avatarUrl:
          "https://s.gravatar.com/avatar/4aeef6ff7b072193b1d2d9fdf9c2be1f?s=480&r=pg&d=https%3A%2F%2Fcdn.auth0.com%2Favatars%2Ffy.png",
      },
    },
    {
      id: "cmeap652804z801l7ea7a3r9l",
      scope: "WORKSPACE",
      scopeEntityId: "clx9g3xak000w01ksr29jl6f2",
      objectType: "VARIABLE",
      objectKey: "email_recipients",
      variable: {
        value: '["data-team@company.com", "ops@company.com"]',
        description: "List of email recipients for alerts",
        isSecret: false,
      },
      createdAt: "2025-08-14T01:05:01.473Z",
      updatedAt: "2025-08-14T01:05:01.473Z",
      createdBy: {
        id: "cmabpzugt019v01jfm2pg8isx",
        subjectType: "USER",
        username: "admin@astronomer.io",
        fullName: "Admin User",
        avatarUrl:
          "https://s.gravatar.com/avatar/0000000000000000000000000000000?s=480&r=pg&d=https%3A%2F%2Fcdn.auth0.com%2Favatars%2Fau.png",
      },
      updatedBy: {
        id: "cmabpzugt019v01jfm2pg8isx",
        subjectType: "USER",
        username: "admin@astronomer.io",
        fullName: "Admin User",
        avatarUrl:
          "https://s.gravatar.com/avatar/0000000000000000000000000000000?s=480&r=pg&d=https%3A%2F%2Fcdn.auth0.com%2Favatars%2Fau.png",
      },
    },
    {
      id: "cm9ab4k2p01xy01n3fg8h5jql",
      scope: "WORKSPACE",
      scopeEntityId: "clx9g3xak000w01ksr29jl6f2",
      objectType: "VARIABLE",
      objectKey: "api_base_url",
      variable: {
        value: "https://api.company.com/v2",
        description: "Base URL for external API integrations",
        isSecret: false,
      },
      links: [
        {
          scope: "DEPLOYMENT",
          scopeEntityId: "clyz2mshy00e501p1vchz64yx",
          variableOverrides: {
            value: "https://api-staging.company.com/v2",
          },
        },
      ],
      createdAt: "2025-07-15T14:22:33.891Z",
      updatedAt: "2025-07-15T14:22:33.891Z",
      createdBy: {
        id: "cl6zt14k7480291jzcdy0n8xzi",
        subjectType: "USER",
        username: "ryan@astronomer.io",
        fullName: "Ryan Hamilton",
        avatarUrl:
          "https://s.gravatar.com/avatar/6dea52b82fbf78cb2eefda489027ef79?s=480&r=pg&d=https%3A%2F%2Fcdn.auth0.com%2Favatars%2Frh.png",
      },
      updatedBy: {
        id: "cl6zt14k7480291jzcdy0n8xzi",
        subjectType: "USER",
        username: "ryan@astronomer.io",
        fullName: "Ryan Hamilton",
        avatarUrl:
          "https://s.gravatar.com/avatar/6dea52b82fbf78cb2eefda489027ef79?s=480&r=pg&d=https%3A%2F%2Fcdn.auth0.com%2Favatars%2Frh.png",
      },
    },
    {
      id: "cm8p5q7r9023k01pq9xyz4mnw",
      scope: "WORKSPACE",
      scopeEntityId: "clx9g3xak000w01ksr29jl6f2",
      objectType: "VARIABLE",
      objectKey: "data_retention_days",
      variable: {
        value: "90",
        description: "Number of days to retain processed data",
        isSecret: false,
      },
      createdAt: "2025-05-20T09:45:12.567Z",
      updatedAt: "2025-05-20T09:45:12.567Z",
      createdBy: {
        id: "cm8nliy1v020n01mirihbvj5y",
        subjectType: "USER",
        username: "william.shi@astronomer.io",
        fullName: "William Shi",
        avatarUrl:
          "https://lh3.googleusercontent.com/a/ACg8ocJ2NpziJkxWB7meKW490TElsJLPn5SnqwQX3XmqLOZ4JjUdsg=s96-c",
      },
      updatedBy: {
        id: "cm8nliy1v020n01mirihbvj5y",
        subjectType: "USER",
        username: "william.shi@astronomer.io",
        fullName: "William Shi",
        avatarUrl:
          "https://lh3.googleusercontent.com/a/ACg8ocJ2NpziJkxWB7meKW490TElsJLPn5SnqwQX3XmqLOZ4JjUdsg=s96-c",
      },
    },
    {
      id: "cm7n8k3lm019s01qw7bc9xptv",
      scope: "WORKSPACE",
      scopeEntityId: "clx9g3xak000w01ksr29jl6f2",
      objectType: "VARIABLE",
      objectKey: "api_rate_limit",
      variable: {
        value: "1000",
        description: "API rate limit per hour",
        isSecret: false,
      },
      createdAt: "2025-04-10T11:30:45.123Z",
      updatedAt: "2025-08-01T16:20:30.789Z",
      createdBy: {
        id: "cl7qqe4tf264442d28fttoe7g8",
        subjectType: "USER",
        username: "vandy.liu@astronomer.io",
        fullName: "Vandy Liu",
        avatarUrl:
          "https://s.gravatar.com/avatar/ea0265af113c7429c02cf1de98f03552?s=480&r=pg&d=https%3A%2F%2Fcdn.auth0.com%2Favatars%2Fvl.png",
      },
      updatedBy: {
        id: "cl6zt14k7480291jzcdy0n8xzi",
        subjectType: "USER",
        username: "ryan@astronomer.io",
        fullName: "Ryan Hamilton",
        avatarUrl:
          "https://s.gravatar.com/avatar/6dea52b82fbf78cb2eefda489027ef79?s=480&r=pg&d=https%3A%2F%2Fcdn.auth0.com%2Favatars%2Frh.png",
      },
    },
    {
      id: "cm6k2x9wy012l01nm5pqr8stc",
      scope: "WORKSPACE",
      scopeEntityId: "clx9g3xak000w01ksr29jl6f2",
      objectType: "VARIABLE",
      objectKey: "enable_debug_mode",
      variable: {
        value: "false",
        description: "Enable debug logging for troubleshooting",
        isSecret: false,
      },
      links: [
        {
          scope: "DEPLOYMENT",
          scopeEntityId: "clyz2mshy00e501p1vchz64yx",
          variableOverrides: {
            value: "true",
          },
        },
      ],
      createdAt: "2025-03-12T08:15:22.456Z",
      updatedAt: "2025-03-12T08:15:22.456Z",
      createdBy: {
        id: "ckx6ogzn059721g078uxv3a7k",
        subjectType: "USER",
        username: "frank.ye@astronomer.io",
        fullName: "Frank Ye",
        avatarUrl:
          "https://s.gravatar.com/avatar/4aeef6ff7b072193b1d2d9fdf9c2be1f?s=480&r=pg&d=https%3A%2F%2Fcdn.auth0.com%2Favatars%2Ffy.png",
      },
      updatedBy: {
        id: "ckx6ogzn059721g078uxv3a7k",
        subjectType: "USER",
        username: "frank.ye@astronomer.io",
        fullName: "Frank Ye",
        avatarUrl:
          "https://s.gravatar.com/avatar/4aeef6ff7b072193b1d2d9fdf9c2be1f?s=480&r=pg&d=https%3A%2F%2Fcdn.auth0.com%2Favatars%2Ffy.png",
      },
    },
    {
      id: "cm5j7w8px015y01op3klm6rst",
      scope: "WORKSPACE",
      scopeEntityId: "clx9g3xak000w01ksr29jl6f2",
      objectType: "VARIABLE",
      objectKey: "db_connection_timeout",
      variable: {
        value: "30",
        description: "Database connection timeout in seconds",
        isSecret: false,
      },
      createdAt: "2025-02-18T13:40:55.234Z",
      updatedAt: "2025-02-18T13:40:55.234Z",
      createdBy: {
        id: "cm8nliy1v020n01mirihbvj5y",
        subjectType: "USER",
        username: "william.shi@astronomer.io",
        fullName: "William Shi",
        avatarUrl:
          "https://lh3.googleusercontent.com/a/ACg8ocJ2NpziJkxWB7meKW490TElsJLPn5SnqwQX3XmqLOZ4JjUdsg=s96-c",
      },
      updatedBy: {
        id: "cm8nliy1v020n01mirihbvj5y",
        subjectType: "USER",
        username: "william.shi@astronomer.io",
        fullName: "William Shi",
        avatarUrl:
          "https://lh3.googleusercontent.com/a/ACg8ocJ2NpziJkxWB7meKW490TElsJLPn5SnqwQX3XmqLOZ4JjUdsg=s96-c",
      },
    },
  ],
  totalCount: 10,
  offset: 0,
  limit: 20,
};
