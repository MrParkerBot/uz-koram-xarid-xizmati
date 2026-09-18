"""Django admin registrations for every record the application keeps."""

from django.contrib import admin

from xarid.models import (
    Application,
    ApplicationItem,
    ArizaStatus,
    Contract,
    ContractItem,
    Department,
    MahsulotTuri,
    Notification,
    PurchaseApplication,
    PurchaseApplicationItem,
    ShartnomaStatus,
    ShartnomaTuri,
    Supplier,
    UserProfile,
    UserSpecialty,
    UserType,
)


class MasterDataAdmin(admin.ModelAdmin):
    list_display = ("name", "category_number", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(UserType)
class UserTypeAdmin(MasterDataAdmin):
    list_display = ("name", "badge_colour", "is_system_role", "is_active")
    list_filter = ("is_active", "is_system_role")


@admin.register(UserSpecialty, ShartnomaTuri, Department)
class PlainMasterDataAdmin(MasterDataAdmin):
    pass


@admin.register(ArizaStatus)
class ArizaStatusAdmin(MasterDataAdmin):
    list_display = ("name", "code", "badge_colour", "position", "is_active")


@admin.register(ShartnomaStatus)
class ShartnomaStatusAdmin(MasterDataAdmin):
    list_display = ("name", "badge_colour", "position", "is_active")


@admin.register(MahsulotTuri)
class MahsulotTuriAdmin(MasterDataAdmin):
    list_display = ("category_number", "name", "is_active")
    search_fields = ("name", "category_number")


@admin.register(Supplier)
class SupplierAdmin(MasterDataAdmin):
    list_display = ("name", "inn", "daraja", "is_active")
    search_fields = ("name", "inn")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "user_type", "department", "phone_number", "may_edit_contracts")
    list_filter = ("user_type", "department", "may_edit_contracts")
    search_fields = ("user__username", "user__first_name", "user__last_name")
    autocomplete_fields = ("user",)


class ApplicationItemInline(admin.TabularInline):
    model = ApplicationItem
    extra = 0


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "ariza_raqami",
        "department",
        "stage",
        "status",
        "assigned_to",
        "kelib_tushgan_sana",
    )
    list_filter = ("stage", "department")
    search_fields = ("ariza_raqami", "buyurtmachi_ismi")
    inlines = (ApplicationItemInline,)
    readonly_fields = ("kelib_tushgan_sana",)


class ContractItemInline(admin.TabularInline):
    model = ContractItem
    extra = 0


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = (
        "shartnoma_raqami",
        "application",
        "supplier",
        "stage",
        "qiymati",
        "yaratilingan_sana",
    )
    list_filter = ("stage", "supplier")
    search_fields = ("shartnoma_raqami",)
    inlines = (ContractItemInline,)
    readonly_fields = ("yaratilingan_sana",)


class PurchaseApplicationItemInline(admin.TabularInline):
    model = PurchaseApplicationItem
    extra = 0


@admin.register(PurchaseApplication)
class PurchaseApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "xarid_raqami",
        "shartnoma_nomi",
        "department",
        "stage",
        "created_by",
        "yaratilingan_sana",
    )
    list_filter = ("stage", "department")
    search_fields = ("xarid_raqami", "shartnoma_nomi")
    inlines = (PurchaseApplicationItemInline,)
    readonly_fields = ("yaratilingan_sana",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "kind",
        "recipient",
        "application",
        "purchase_application",
        "created_at",
        "read_at",
    )
    list_filter = ("kind",)
