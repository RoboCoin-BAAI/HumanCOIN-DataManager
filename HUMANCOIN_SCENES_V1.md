# HumanCOIN 场景分类词表 V1

category 为固定枚举，area 为开放 snake_case 词表，优先使用以下典型值。以下按用户最终清单完整保留：6 大类共 42 个典型 area，加两组兜底。

| category | 中文 | 典型 area |
|---|---|---|
| household | 家庭生活 | kitchen、dining_area、living_room、bedroom、bathroom、household_storage |
| commercial_service | 商业服务 | retail_store、restaurant、cafe、hotel、hair_salon、beauty_salon、warehouse、sorting_area、packing_area、shelving_area、loading_area、delivery_area |
| industrial_production | 工业生产 | assembly、machining、inspection、maintenance、workshop、construction |
| professional_work | 专业工作 | office、laboratory、classroom、medical_area、care_area、studio |
| public_outdoor | 公共与户外 | street、transportation、public_facility、garden、farm、sports_area |
| leisure_social | 休闲与社交 | sports_venue、gaming_area、music_venue、entertainment_area、social_gathering、pet_service |
| other | 已知但无法归入现有大类 | other |
| unknown | 场景未知或无法判断 | unknown |

允许为六大类新增 area（例如 shoe_repair），不允许新增 category；已知典型 area 必须归入表中的对应大类。兜底 category 与 area 必须同名，area 不为 null。分类描述功能活动场景，不把任务推断当成实地拍摄位置的证明。

机器词表为 humancoin_scenes_v1.json；共用提取器、简智文本结构化、最终 JSON Schema 与光轮文本补全均使用本版规则。光轮仓库保存同内容词表副本。

已有数据不会自动迁移，旧 category 或不兼容的 area 可能无法通过新 Schema；需显式重新结构化或迁移，不能只改 category 而忽略 area。
