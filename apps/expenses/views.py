"""API views for the expenses app."""
import hashlib

from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.api.mixins import ApiResponseMixin, FarmAccessMixin
from apps.core.validators import reencode_image, sniff_mime
from apps.expenses.models import (
    ElectricityBill,
    ExpenseCategory,
    ExpenseDocument,
    FarmExpense,
    FarmExpenseSummary,
    FuelExpense,
    InputExpense,
    LabourExpense,
    RentalExpense,
    TransportExpense,
)
from apps.expenses.serializers import (
    ElectricityBillSerializer,
    FarmExpenseSerializer,
    FarmExpenseSummarySerializer,
    FuelExpenseSerializer,
    InputExpenseSerializer,
    LabourExpenseSerializer,
    RentalExpenseSerializer,
    TransportExpenseSerializer,
)
from apps.expenses.services import ExpenseAggregationService, expand_typed_expenses
from apps.ml_engine.services.expense_analysis import ExpenseAnalysisService


def _resolve_expense_category(value):
    """Resolve a client-supplied ExpenseCategory reference to a row.

    Accepts a primary key (what a naive client sends) or a stable ``code``
    (what the upload picker sends, and what stays readable in a log). Returns
    ``(instance_or_None, errors_or_None)``.

    This used to be ``category_id=request.data.get("category")``, which pushed
    a slug straight into a UUID foreign key: Django raised ValueError and the
    farmer got a 500 for picking "Electricity bill" from the dropdown.
    """
    if value in (None, ""):
        return None, None
    text = str(value).strip()
    if not text:
        return None, None

    row = None
    try:
        row = ExpenseCategory.objects.filter(pk=text).first()
    except (ValueError, ValidationError, DjangoValidationError):
        row = None
    if row is None:
        row = ExpenseCategory.objects.filter(code__iexact=text).first()
    if row is None:
        return None, [{"field": "category", "message": f"Unknown expense category '{text}'."}]
    return row, None


class _GenericExpenseView(ApiResponseMixin, FarmAccessMixin):
    permission_classes = [IsAuthenticated]
    serializer_class = FarmExpenseSerializer
    model = FarmExpense

    def get(self, request, farm_id):
        farm = self.get_farm()
        return self.respond(data=self.serializer_class(self.model.objects.filter(farm=farm), many=True).data, message="Expenses retrieved.")

    def post(self, request, farm_id):
        farm = self.get_farm()
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(farm=farm, created_by=request.user)
        return self.respond(data=serializer.data, message="Expense saved.", status_code=status.HTTP_201_CREATED)


class ExpenseListView(_GenericExpenseView):
    """List and create plain FarmExpense rows for a farm.

    GET returns every row in creation order with no filtering or pagination;
    POST stamps farm and created_by from the resolved farm, so a client cannot
    file an expense against a farm it does not own.
    """

    serializer_class = FarmExpenseSerializer
    model = FarmExpense


class ElectricityBillView(_GenericExpenseView):
    """List and create electricity bill entries.

    Same generic list/create behaviour, but the serializer exposes the
    provider-specific fields (provider, units_kwh, bill_month) and leaves
    tariff_effective_per_kwh read-only so it stays derived.
    """

    serializer_class = ElectricityBillSerializer
    model = ElectricityBill


class FuelExpenseView(_GenericExpenseView):
    """List and create fuel entries.

    Adds litre_volume, price_per_litre and fuel_type to the generic behaviour;
    rows are returned unfiltered and unpaginated.
    """

    serializer_class = FuelExpenseSerializer
    model = FuelExpense


class InputExpenseView(_GenericExpenseView):
    """List and create input purchases (seed, fertilizer, chemicals).

    Records input_type and product_name with quantity and unit; GET returns
    every row for the farm with no date or type filtering.
    """

    serializer_class = InputExpenseSerializer
    model = InputExpense


class LabourExpenseView(_GenericExpenseView):
    """List and create labour cost entries.

    Captures person_days and wage_per_day alongside the amount; GET returns
    all labour rows for the farm unfiltered.
    """

    serializer_class = LabourExpenseSerializer
    model = LabourExpense


class TransportExpenseView(_GenericExpenseView):
    """List and create transport entries.

    Stores vehicle_type and distance_km with the amount; no aggregation or
    per-vehicle grouping is applied on read.
    """

    serializer_class = TransportExpenseSerializer
    model = TransportExpense


class RentalExpenseView(_GenericExpenseView):
    """List and create equipment rental entries.

    rental_hours and rental_days are both optional, so the same endpoint
    covers hourly and daily hire; GET returns every row unpaginated.
    """

    serializer_class = RentalExpenseSerializer
    model = RentalExpense


class ExpenseDocumentView(ApiResponseMixin, FarmAccessMixin):
    """Upload a receipt or bill image/PDF against a farm.

    The file is read fully into memory to compute a sha256 content hash and
    size, then rewound for storage. Size and extension are validated, and the
    optional category accepts a primary key or a stable code; an unknown value
    is rejected rather than silently dropped. Write-only, no read endpoint.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, farm_id):
        farm = self.get_farm()
        document = request.FILES.get("document")
        if not document:
            return self.respond_error([{"field": "document", "message": "document file is required."}])
        from apps.core.validators import validate_document_extension, validate_upload_file_size

        validate_upload_file_size(document)
        validate_document_extension(document.name)
        content = document.read()
        document.seek(0)
        category, category_error = _resolve_expense_category(request.data.get("category"))
        if category_error:
            return self.respond_error(category_error)
        obj = ExpenseDocument.objects.create(
            farm=farm,
            document=document,
            original_name=document.name,
            content_hash=hashlib.sha256(content).hexdigest(),
            file_size=len(content),
            category=category,
            created_by=request.user,
        )
        return self.respond(data={"document_id": str(obj.id), "original_name": obj.original_name, "status": "uploaded"}, message="Document uploaded.", status_code=status.HTTP_201_CREATED)


class ExpenseCategoryListView(ApiResponseMixin, FarmAccessMixin):
    """The filing options offered by the receipt-upload picker.

    ``ExpenseDocument.category`` is a UUID FK, but the picker is driven by the
    stable ``code`` so the stored labels can be re-worded freely. Handing the
    client both keeps the upload POST readable and lets a future custom
    category appear without a frontend release.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, farm_id):
        self.get_farm()
        rows = ExpenseCategory.objects.all()
        data = [
            {"id": str(row.id), "code": row.code, "name": row.name, "is_custom": row.is_custom}
            for row in rows
        ]
        return self.respond(data=data, message="Expense categories retrieved.")


class ExpenseSummaryView(ApiResponseMixin, FarmAccessMixin):
    """Totals and per-category breakdown for a farm's expenses.

    Recomputed on every request by ExpenseAggregationService from the base
    expense rows plus their typed subclasses; nothing is cached or persisted
    here. An optional year query param narrows the window, otherwise all
    recorded years are summarised.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, farm_id):
        farm = self.get_farm()
        year = request.query_params.get("year")
        service = ExpenseAggregationService(farm.id, year=int(year) if year else None)
        result = service.summarize()
        return self.respond(data=result, message="Expense summary computed.")


class ExpenseAnalysisView(ApiResponseMixin, FarmAccessMixin):
    """Per-category spending anomaly detection for a farm.

    Runs the anomaly detector on every call, using isolation forest when
    scikit-learn is available and an IQR baseline otherwise; models_used
    reports which one ran. The result is returned for review only, nothing is
    flagged as an error or corrected.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, farm_id):
        farm = self.get_farm()
        service = ExpenseAnalysisService(farm)
        analysis = service.run_analysis()
        return self.respond(data=analysis, message="Expense analysis computed.")