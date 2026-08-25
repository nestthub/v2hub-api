                         PROVIDER BOT
                              │
                              │ request(user_id)
                              ▼
                         API SERVER
                              │
                              ▼
                    ┌─────────────────────┐
                    │ User exists by      │
                    │ user_id?            │
                    └────┬──────────┬─────┘
                         │          │
                        yes        no
                         │          │
                         │          ▼
                         │     generate HMAC
                         │          │
                         │          ▼
                         │     return:
                         │     conn_{hmac[:24]}_{provider_name}
                         │
                         ▼
              ┌─────────────────────────┐
              │ Authorization exists?   │
              └────────┬─────────┬──────┘
                       │         │
                      no        yes
                       │         │
                       ▼         └──────────────────────────┐
                  create PENDING                            │
                       │                                    │
                       └────────────────┬───────────────────┘
                                        │
                                        ▼
                               return:
                               provider_{provider_name}
                                        │
                                        ▼
                                      USER
                                        │
                                        │ opens link
                                        ▼
                                   ADMIN BOT
                                        │
                                        │ parse start
                                        │
                     ┌──────────────────┴──────────────────┐
                     │                                     │
                     ▼                                     ▼
          provider_{provider_name}             conn_{hmac[:24]}_{provider_name}
                     │                                     │
                     └──────────────────┬──────────────────┘
                                        │
                                        │ request(
                                        │   user_id,
                                        │   provider_name,
                                        │   hmac?
                                        │ )
                                        ▼
                                   API SERVER
                                        │
                                        ▼
                              ┌─────────────────────┐
                              │ User exists by      │
                              │ user_id?            │
                              └────┬──────────┬─────┘
                                   │          │
                                  yes        no
                                   │          │
                                   │          ▼
                                   │      create user
                                   │          │
                                   └────┬─────┘
                                        │
                                        ▼
                              ┌─────────────────────┐
                              │ provider_name       │
                              │ is valid?           │
                              └────┬─────────┬──────┘
                                   │         │
                                  yes       no
                                   │         │
                                   │         ▼
                                   │       return None
                                   │
                                   ▼
                              ┌─────────────────────┐
                              │ hmac was provided   │
                              │ and is valid?       │
                              └────┬───────────┬────┘
                                   │           │
                                  yes          no
                                   │           │
                                   ▼           │
                         ┌──────────────────┐  │
                         │ Authorization    │  │
                         │ exists?          │  │
                         └────┬────────┬────┘  │
                              │        │       │
                             no       yes      │
                              │        │       │
                              ▼        │       │
                         create        │       │
                         PENDING       │       │
                              │        │       │
                              └────┬───┘       │
                                   │           │
                                   └─────┬─────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │ Authorization       │
                              │ exists?             │
                              └────┬──────────┬─────┘
                                   │          │
                                  no         yes
                                   │          │
                                   ▼          ▼
                               return     return current
                                None          status
                                   │          │
                                   └────┬─────┘
                                        │
                                        ▼
                               return status / None
                                        │
                                        ▼
                                   ADMIN BOT
                     ┌──────────────────┼──────────────────┬───────────────┐
                     │                  │                  │               │
                     ▼                  ▼                  ▼               ▼
                  PENDING             None            other status       ERROR
                     │                  │                  │               │
                     ▼                  └────────┬─────────┘               ▼
            provider information               │                      MAIN MENU
            + connection offer                 │
                     │                         │
                     │                         ▼
                     │                provider information
                     │
                     ▼
             ┌───────────────────┐
             │ User decision     │
             └─────────┬─────────┘
                       │
                ┌──────┴──────┐
                │             │
                ▼             ▼
             APPROVE        REJECT
                │             │
                └──────┬──────┘
                       │
                       │ request(
                       │   user_id,
                       │   provider_name,
                       │   decision
                       │ )
                       ▼
                  API SERVER
                       │
                       ▼
              ┌─────────────────────┐
              │ Authorization       │
              │ exists?             │
              └───────┬───────┬─────┘
                     yes      no
                      │        │
                      │        ▼
                      │      ERROR
                      │
                      ▼
              ┌─────────────────────┐
              │ User decision       │
              └───────┬───────┬─────┘
                      │       │
                   APPROVE  REJECT
                      │       │
                      ▼       ▼
                  set status  ┌────────────────────────────┐
                  APPROVED    │ Subscriptions exist for    │
                      │       │ provider-user relation?    │
                      │       └────────────┬───────────────┘
                      │                    │
                      │              ┌─────┴─────┐
                      │             yes         no
                      │              │           │
                      │              ▼           ▼
                      │         set status     delete
                      │          REVOKED     authorization
                      │              │           │
                      └──────────────┴─────┬─────┘
                                           │
                                           ▼
                                     return status
                                           │
                                           ▼
                                      ADMIN BOT
                                           │
                                           ▼
                                  show result to user
