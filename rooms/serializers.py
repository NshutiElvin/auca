from rest_framework import serializers
from rooms.models import Location, Room, RoomAllocationSwitch

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