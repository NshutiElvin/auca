from django.contrib import admin
from .models import Location, Room, RoomAllocationSwitch


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("name", "capacity", "rows", "columns", "location")
    list_editable = ("capacity", "rows", "columns")
    list_filter = ("location",)
    search_fields = ("name",)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(RoomAllocationSwitch)
class RoomAllocationSwitchAdmin(admin.ModelAdmin):
    list_display = ("is_enabled",)
