# Database schema

Generated from the models by `python manage.py delivery_docs`. Do not edit by
hand: `python manage.py delivery_docs --check` fails when this file and the
code disagree, and the test suite runs that check.

Deletion is deactivation everywhere (DEC-009), so no table here has rows
removed by the application.

## `xarid_application` - Ariza

| Column | Type | Rules | References |
| --- | --- | --- | --- |
| `id` | BigAutoField | primary key |  |
| `ariza_raqami` | CharField | unique |  |
| `department_id` | ForeignKey |  | -> `xarid_department` |
| `buyurtmachi_ismi` | CharField |  |  |
| `izoh` | TextField |  |  |
| `pdf` | FileField |  |  |
| `sender_id` | ForeignKey | null | -> `auth_user` |
| `status_id` | ForeignKey | null | -> `xarid_arizastatus` |
| `kelib_tushgan_sana` | DateTimeField |  |  |
| `qabul_qilingan_sana` | DateTimeField | null |  |
| `accepted_by_id` | ForeignKey | null | -> `auth_user` |
| `inkor_izohi` | TextField |  |  |
| `inkor_qilingan_sana` | DateTimeField | null |  |
| `rejected_by_id` | ForeignKey | null | -> `auth_user` |
| `assigned_to_id` | ForeignKey | null | -> `auth_user` |
| `xodim_qabul_qilgan_sana` | DateTimeField | null |  |
| `tayinlangan_sana` | DateTimeField | null |  |
| `assigned_by_id` | ForeignKey | null | -> `auth_user` |
| `stage` | CharField |  |  |

## `xarid_applicationitem` - Ariza qatori

| Column | Type | Rules | References |
| --- | --- | --- | --- |
| `id` | BigAutoField | primary key |  |
| `buyurtma_nomi` | CharField |  |  |
| `buyurtma_soni` | DecimalField |  |  |
| `olchov_birligi` | CharField |  |  |
| `application_id` | ForeignKey |  | -> `xarid_application` |
| `mahsulot_turi_id` | ForeignKey |  | -> `xarid_mahsulotturi` |

## `xarid_arizastatus` - Ariza Status

| Column | Type | Rules | References |
| --- | --- | --- | --- |
| `id` | BigAutoField | primary key |  |
| `category_number` | PositiveIntegerField | null |  |
| `is_active` | BooleanField |  |  |
| `created_at` | DateTimeField |  |  |
| `badge_colour` | CharField |  |  |
| `position` | PositiveIntegerField |  |  |
| `name` | CharField | unique |  |
| `code` | CharField |  |  |

## `xarid_auditentry` - Log yozuvi

| Column | Type | Rules | References |
| --- | --- | --- | --- |
| `id` | BigAutoField | primary key |  |
| `actor_id` | ForeignKey |  | -> `auth_user` |
| `actor_department_id` | ForeignKey | null | -> `xarid_department` |
| `form_name` | CharField |  |  |
| `record_label` | CharField |  |  |
| `record_type` | CharField |  |  |
| `record_id` | PositiveIntegerField |  |  |
| `action` | CharField |  |  |
| `created_at` | DateTimeField |  |  |
| `approver_id` | ForeignKey | null | -> `auth_user` |
| `approver_department_id` | ForeignKey | null | -> `xarid_department` |
| `approval_comment` | TextField |  |  |
| `approved_at` | DateTimeField | null |  |
| `approval_outcome` | CharField |  |  |

## `xarid_contract` - Shartnoma

| Column | Type | Rules | References |
| --- | --- | --- | --- |
| `id` | BigAutoField | primary key |  |
| `shartnoma_raqami` | CharField | unique |  |
| `application_id` | ForeignKey |  | -> `xarid_application` |
| `supplier_id` | ForeignKey |  | -> `xarid_supplier` |
| `shartnoma_turi_id` | ForeignKey | null | -> `xarid_shartnomaturi` |
| `qiymati` | DecimalField |  |  |
| `status_id` | ForeignKey | null | -> `xarid_shartnomastatus` |
| `stage` | CharField |  |  |
| `inkor_izohi` | TextField |  |  |
| `yuborilgan_sana` | DateTimeField | null |  |
| `yuborgan_id` | ForeignKey | null | -> `auth_user` |
| `tasdiqlagan_id` | ForeignKey | null | -> `auth_user` |
| `tasdiqlangan_sana` | DateTimeField | null |  |
| `inkor_qilgan_id` | ForeignKey | null | -> `auth_user` |
| `inkor_sanasi` | DateTimeField | null |  |
| `yuborishlar_soni` | PositiveIntegerField |  |  |
| `created_by_id` | ForeignKey |  | -> `auth_user` |
| `shartnoma_sanasi` | DateField | null |  |
| `tolash_muddati` | DateField | null |  |
| `invoice_sanasi` | DateField | null |  |
| `muddat_talabi` | DateField | null |  |
| `izoh` | TextField |  |  |
| `pdf` | FileField |  |  |
| `yaratilingan_sana` | DateTimeField |  |  |

## `xarid_contractitem` - Shartnoma qatori

| Column | Type | Rules | References |
| --- | --- | --- | --- |
| `id` | BigAutoField | primary key |  |
| `buyurtma_nomi` | CharField |  |  |
| `buyurtma_soni` | DecimalField |  |  |
| `olchov_birligi` | CharField |  |  |
| `contract_id` | ForeignKey |  | -> `xarid_contract` |
| `part_number` | CharField |  |  |
| `narxi` | DecimalField |  |  |

## `xarid_contractstatuschange` - Shartnoma holati o`zgarishi

| Column | Type | Rules | References |
| --- | --- | --- | --- |
| `id` | BigAutoField | primary key |  |
| `contract_id` | ForeignKey |  | -> `xarid_contract` |
| `from_status_id` | ForeignKey | null | -> `xarid_shartnomastatus` |
| `to_status_id` | ForeignKey |  | -> `xarid_shartnomastatus` |
| `changed_by_id` | ForeignKey |  | -> `auth_user` |
| `changed_at` | DateTimeField |  |  |

## `xarid_department` - Bo`lim

| Column | Type | Rules | References |
| --- | --- | --- | --- |
| `id` | BigAutoField | primary key |  |
| `category_number` | PositiveIntegerField | null |  |
| `is_active` | BooleanField |  |  |
| `created_at` | DateTimeField |  |  |
| `name` | CharField | unique |  |

## `xarid_mahsulotturi` - Mahsulot Turi

| Column | Type | Rules | References |
| --- | --- | --- | --- |
| `id` | BigAutoField | primary key |  |
| `is_active` | BooleanField |  |  |
| `created_at` | DateTimeField |  |  |
| `category_number` | PositiveIntegerField | unique |  |
| `name` | CharField | unique |  |
| `description` | TextField |  |  |

## `xarid_notification` - Bildirishnoma

| Column | Type | Rules | References |
| --- | --- | --- | --- |
| `id` | BigAutoField | primary key |  |
| `recipient_id` | ForeignKey |  | -> `auth_user` |
| `application_id` | ForeignKey | null | -> `xarid_application` |
| `purchase_application_id` | ForeignKey | null | -> `xarid_purchaseapplication` |
| `kind` | CharField |  |  |
| `izoh` | TextField |  |  |
| `created_at` | DateTimeField |  |  |
| `read_at` | DateTimeField | null |  |

## `xarid_purchaseapplication` - Xarid arizasi

| Column | Type | Rules | References |
| --- | --- | --- | --- |
| `id` | BigAutoField | primary key |  |
| `xarid_raqami` | CharField | unique |  |
| `shartnoma_nomi` | CharField |  |  |
| `department_id` | ForeignKey |  | -> `xarid_department` |
| `muddat_talabi` | DateField | null |  |
| `izoh` | TextField |  |  |
| `pdf` | FileField |  |  |
| `asl_pdf` | FileField |  |  |
| `status_id` | ForeignKey | null | -> `xarid_arizastatus` |
| `created_by_id` | ForeignKey |  | -> `auth_user` |
| `yaratilingan_sana` | DateTimeField |  |  |
| `stage` | CharField |  |  |
| `tasdiqlagan_bolim_boshligi_id` | ForeignKey | null | -> `auth_user` |
| `bolim_boshligi_sanasi` | DateTimeField | null |  |
| `tasdiqlagan_direktor_id` | ForeignKey | null | -> `auth_user` |
| `direktor_sanasi` | DateTimeField | null |  |
| `inkor_izohi` | TextField |  |  |
| `inkor_qilgan_id` | ForeignKey | null | -> `auth_user` |
| `inkor_sanasi` | DateTimeField | null |  |
| `raised_application_id` | OneToOneField | unique, null | -> `xarid_application` |

## `xarid_purchaseapplicationitem` - Xarid arizasi qatori

| Column | Type | Rules | References |
| --- | --- | --- | --- |
| `id` | BigAutoField | primary key |  |
| `buyurtma_nomi` | CharField |  |  |
| `buyurtma_soni` | DecimalField |  |  |
| `olchov_birligi` | CharField |  |  |
| `application_id` | ForeignKey |  | -> `xarid_purchaseapplication` |
| `mahsulot_turi_id` | ForeignKey |  | -> `xarid_mahsulotturi` |

## `xarid_shartnomastatus` - Shartnoma Status

| Column | Type | Rules | References |
| --- | --- | --- | --- |
| `id` | BigAutoField | primary key |  |
| `category_number` | PositiveIntegerField | null |  |
| `is_active` | BooleanField |  |  |
| `created_at` | DateTimeField |  |  |
| `badge_colour` | CharField |  |  |
| `position` | PositiveIntegerField |  |  |
| `name` | CharField | unique |  |
| `is_completed` | BooleanField |  |  |

## `xarid_shartnomaturi` - Shartnoma Turi

| Column | Type | Rules | References |
| --- | --- | --- | --- |
| `id` | BigAutoField | primary key |  |
| `category_number` | PositiveIntegerField | null |  |
| `is_active` | BooleanField |  |  |
| `created_at` | DateTimeField |  |  |
| `name` | CharField | unique |  |

## `xarid_supplier` - Firma

| Column | Type | Rules | References |
| --- | --- | --- | --- |
| `id` | BigAutoField | primary key |  |
| `category_number` | PositiveIntegerField | null |  |
| `is_active` | BooleanField |  |  |
| `created_at` | DateTimeField |  |  |
| `name` | CharField | unique |  |
| `inn` | CharField |  |  |
| `daraja` | CharField |  |  |

## `xarid_userprofile` - User Profile

| Column | Type | Rules | References |
| --- | --- | --- | --- |
| `id` | BigAutoField | primary key |  |
| `user_id` | OneToOneField | unique | -> `auth_user` |
| `user_type_id` | ForeignKey | null | -> `xarid_usertype` |
| `department_id` | ForeignKey | null | -> `xarid_department` |
| `phone_number` | CharField |  |  |
| `may_edit_contracts` | BooleanField |  |  |

## `xarid_userspecialty` - User Specialty

| Column | Type | Rules | References |
| --- | --- | --- | --- |
| `id` | BigAutoField | primary key |  |
| `category_number` | PositiveIntegerField | null |  |
| `is_active` | BooleanField |  |  |
| `created_at` | DateTimeField |  |  |
| `name` | CharField | unique |  |

## `xarid_usertype` - User Type

| Column | Type | Rules | References |
| --- | --- | --- | --- |
| `id` | BigAutoField | primary key |  |
| `category_number` | PositiveIntegerField | null |  |
| `is_active` | BooleanField |  |  |
| `created_at` | DateTimeField |  |  |
| `name` | CharField | unique |  |
| `badge_colour` | CharField |  |  |
| `is_system_role` | BooleanField |  |  |
