from rest_framework import serializers
from rooms.models import Location, Room, RoomAllocationSwitch, RoomOutOfService

from django.contrib.auth import get_user_model

User = get_user_model()

class RoomAllocationSwitchSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomAllocationSwitch
        fields = '__all__'

class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model =Location
        fields = '__all__'

class RoomSerializer(serializers.ModelSerializer):
    location= LocationSerializer(read_only=True)
    location_id = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), source='location',
        write_only=True, required=False, allow_null=True,
    )
    class Meta:
        model = Room
        fields = '__all__'

    def validate(self, attrs):
        rows = attrs.get('rows', getattr(self.instance, 'rows', None))
        columns = attrs.get('columns', getattr(self.instance, 'columns', None))
        capacity = attrs.get('capacity', getattr(self.instance, 'capacity', None))

        if bool(rows) != bool(columns):
            raise serializers.ValidationError(
                "Both 'rows' and 'columns' must be set together, or left both empty."
            )

        if rows and columns and capacity and rows * columns < capacity:
            raise serializers.ValidationError(
                f"Room layout ({rows}x{columns}={rows * columns} seats) cannot fit "
                f"the declared capacity ({capacity})."
            )

        return attrs


class RoomOutOfServiceSerializer(serializers.ModelSerializer):
    room_name = serializers.CharField(source='room.name', read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = RoomOutOfService
        fields = [
            'id', 'room', 'room_name', 'start_date', 'end_date',
            'start_time', 'end_time', 'reason', 'created_by',
            'created_by_name', 'created_at',
        ]
        read_only_fields = ['created_by']

    def get_created_by_name(self, obj):
        if not obj.created_by:
            return None
        return f"{obj.created_by.first_name} {obj.created_by.last_name}".strip() or obj.created_by.email

    def validate(self, attrs):
        start_date = attrs.get('start_date', getattr(self.instance, 'start_date', None))
        end_date = attrs.get('end_date', getattr(self.instance, 'end_date', None))
        start_time = attrs.get('start_time', getattr(self.instance, 'start_time', None))
        end_time = attrs.get('end_time', getattr(self.instance, 'end_time', None))

        if start_date and end_date and start_date > end_date:
            raise serializers.ValidationError("'start_date' must not be after 'end_date'.")
        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError("'start_time' must be before 'end_time'.")

        return attrs