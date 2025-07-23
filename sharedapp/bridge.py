from .serializers import UnscheduledExamGroupSerializer
class MyUnscheduledExamGroupSerializer(UnscheduledExamGroupSerializer):
    def __init__(self, instance=None, data=..., **kwargs):
        super().__init__(instance, data, **kwargs)