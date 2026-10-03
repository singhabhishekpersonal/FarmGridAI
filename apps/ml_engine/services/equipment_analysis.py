"""Equipment analysis pipeline: classify image -> extract OCR -> assess condition.

Every step records a PredictionAuditLog. A real model artifact is optional;
the service degrades to rule-based fallbacks that always ask for confirmation.
"""
import logging

from apps.equipment.models import EquipmentConditionAssessment, EquipmentImagePrediction, EquipmentOCRResult
from apps.ml_engine.registry import log_prediction
from apps.ml_engine.vision.classifier import classify_image

logger = logging.getLogger("FarmGrid")


class EquipmentAnalysisService:
    """Run the full analysis for a single equipment image."""

    def __init__(self, image, user=None):
        self.image = image
        self.equipment = image.equipment
        self.user = user

    # ------------------------------------------------------------------
    TOP6_BRANDS = {"Mahindra", "Sonalika", "Farmtrac", "John Deere", "New Holland", "Powertrac"}

    @classmethod
    def _kind_for_brand(cls, brand):
        """Map a classifier brand label to an equipment-kind class code.

        The CNN predicts *brands*; the stored EquipmentImagePrediction keeps
        predicted_class as an equipment kind (tractor for the six known brands,
        unknown otherwise) and stores the brand separately in predicted_brand.
        """
        if brand in cls.TOP6_BRANDS:
            return "tractor"
        return "unknown"

    def classify(self, persist=True):
        result = classify_image(self.image.image)
        brand = result.get("predicted_brand", "")
        kind = self._kind_for_brand(brand) if brand else result["predicted_class"]
        confidence = float(result.get("confidence_score", 0.0))
        probs = {p["label"]: p["probability"] for p in result.get("top_predictions", [])}
        pred = {
            "predicted_class": kind,
            "predicted_brand": brand,
            "confidence": confidence,
            "class_probabilities": probs,
            "top_predictions": result.get("top_predictions", []),
            "confidence_label": result.get("confidence_label", "low"),
            "used_ml": result.get("used_ml", False),
            "artifact_available": result.get("artifact_available", False),
            "unknown_threshold": result.get("unknown_threshold"),
            "model_name": "MobileNetV3-Large" if result.get("used_ml") else result.get("model_name", "equipment_classifier"),
            "model_version": result.get("model_version", "fallback"),
            "input_hash": self.image.content_hash,
            "source": result.get("source", "fallback"),
            "needs_user_confirmation": True,
            "limitations": result.get("limitations", []),
        }
        # If the equipment already has a known catalog category, prefer its class.
        if self.equipment.catalog and self.equipment.catalog.category_id:
            pred["predicted_class"] = self.equipment.catalog.category.code
            pred["confidence"] = 0.6
            pred["source"] = "catalog_lookup"
            pred["needs_user_confirmation"] = True

        if persist:
            db_pred = {k: v for k, v in pred.items() if k != "limitations"}
            EquipmentImagePrediction.objects.create(image=self.image, created_by=self.user, **db_pred)

        log_prediction(
            user=self.user,
            farm=self.equipment.farm,
            registry_key="equipment_classifier",
            input_type="equipment_image",
            input_snapshot={"image_hash": self.image.content_hash},
            output_snapshot=pred,
            confidence=pred["confidence_label"],
            status="fallback" if pred["source"] in ("fallback", "failed") else "success",
        )
        return pred

    # ------------------------------------------------------------------
    def ocr_extract(self, persist=True):
        from apps.ml_engine.ocr import extract_text, matches_catalog

        result = extract_text(self.image.image)
        matched = False
        if self.equipment.catalog:
            matched, score, token = matches_catalog(result["brand_candidates"] + result["model_candidates"], self.equipment.catalog)
            if matched:
                result["confidence"] = score
        result["needs_user_confirmation"] = True
        if persist:
            EquipmentOCRResult.objects.create(image=self.image, created_by=self.user, **result)
        return result

    # ------------------------------------------------------------------
    def assess_condition(self, persist=True):
        """Visible-condition estimate from rules + image-derived cues.

        Deliberately limited: returns a band + issue tags + confidence, never
        exact mechanical health.
        """
        equipment = self.equipment
        score = 70
        issue_tags = []
        if equipment.condition != "unknown":
            map_band = {"good": 85, "moderate": 55, "poor": 35}
            score = map_band.get(equipment.condition, 70)
        age = equipment.age_years
        if age is not None:
            if age > 15:
                score -= 15
                issue_tags.append("age_over_15_years")
            elif age > 8:
                score -= 6
                issue_tags.append("age_over_8_years")
        if equipment.is_operational is False:
            score -= 10
            issue_tags.append("reported_non_operational")

        band = "good"
        if score <= 40:
            band = "poor"
        elif score <= 60:
            band = "moderate"

        assessment = {
            "visible_condition_score": max(0, min(100, int(score))),
            "condition_band": band,
            "issue_tags": issue_tags,
            "method": "farmer-declared rule-based",
            "confidence": "low",
            "needs_user_confirmation": True,
        }
        if persist:
            EquipmentConditionAssessment.objects.create(equipment=equipment, created_by=self.user, **assessment)
        log_prediction(
            user=self.user,
            farm=equipment.farm,
            registry_key="condition_assessor",
            input_type="equipment_declared_state",
            input_snapshot={"condition": equipment.condition, "age": age, "operational": equipment.is_operational},
            output_snapshot=assessment,
            confidence="low",
            status="success",
        )
        return assessment

    # ------------------------------------------------------------------
    def run_analysis(self, persist=True):
        prediction = self.classify(persist=persist)
        ocr = self.ocr_extract(persist=persist)
        condition = self.assess_condition(persist=persist)
        return {
            "image_id": str(self.image.id),
            "prediction": prediction,
            "ocr": ocr,
            "condition_assessment": condition,
            "platform_note": "Predicted class, brand/model and condition are ESTIMATES requiring confirmation. They are never presented as exact facts.",
        }