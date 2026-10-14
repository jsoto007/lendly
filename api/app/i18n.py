"""Server-side copy in the caller's language (Accept-Language: es → Spanish).

Messages are written in English in the code and looked up here at response time. Dynamic parts
are `{placeholders}` filled after translation, so the templates stay translatable.
"""
from flask import has_request_context, request

SUPPORTED = ("en", "es")

ES = {
    # auth / tenancy
    "Sign in required.": "Inicia sesión para continuar.",
    "Session expired. Sign in again.": "La sesión expiró. Inicia sesión de nuevo.",
    "X-Tenant-Id header is required.": "Falta el encabezado X-Tenant-Id.",
    "You are not a member of this workspace.": "No eres miembro de este espacio de trabajo.",
    "This action needs the lender role.": "Esta acción requiere el rol de prestamista.",
    "Enter a valid email address.": "Ingresa un correo electrónico válido.",
    "That code is wrong or expired.": "Ese código es incorrecto o ya expiró.",
    "Apple sign-in could not be verified.": "No se pudo verificar el inicio de sesión con Apple.",
    "That invite code is invalid or has expired.": "Ese código de invitación no es válido o ya expiró.",
    "This invite was already used by someone else.": "Otra persona ya usó esta invitación.",
    "You already manage this workspace.": "Ya administras este espacio de trabajo.",
    "You're already linked to a different profile in this workspace.": "Ya estás vinculado a otro perfil en este espacio de trabajo.",
    # borrowers / loans / payments
    "Borrower not found.": "No se encontró al prestatario.",
    "Borrower profile not found.": "No se encontró el perfil del prestatario.",
    "Loan not found.": "No se encontró el préstamo.",
    "Payment not found.": "No se encontró el pago.",
    "Receipt not found.": "No se encontró el recibo.",
    "{name} already has access.": "{name} ya tiene acceso.",
    "Unarchive this borrower before creating a loan.": "Desarchiva a este prestatario antes de crear un préstamo.",
    "Unarchive this borrower before inviting them.": "Desarchiva a este prestatario antes de invitarlo.",
    "Terms are locked once a payment has been recorded. Void the payments first.": "Las condiciones quedan bloqueadas una vez registrado un pago. Anula los pagos primero.",
    "Void the recorded payments before cancelling this loan.": "Anula los pagos registrados antes de cancelar este préstamo.",
    "Loans with payment history can't be deleted. Cancel it instead.": "Los préstamos con historial de pagos no se pueden eliminar. Cancélalo en su lugar.",
    "This loan is cancelled. Reactivate it to record payments.": "Este préstamo está cancelado. Reactívalo para registrar pagos.",
    "This loan is already paid off.": "Este préstamo ya está pagado por completo.",
    "Amount exceeds the balance owed on that date ({amount}).": "El monto supera el saldo adeudado en esa fecha ({amount}).",
    "That amount would overpay the loan once interest is recomputed for its date.": "Ese monto pagaría de más el préstamo al recalcular el interés para esa fecha.",
    "This request key was already used for a different payment.": "Esta clave de solicitud ya se usó para un pago distinto.",
    "This payment is already voided.": "Este pago ya fue anulado.",
    "Voided receipts can't be edited.": "Los recibos anulados no se pueden editar.",
    "Payment date can't be in the future.": "La fecha del pago no puede estar en el futuro.",
    "Payment date is before the loan started.": "La fecha del pago es anterior al inicio del préstamo.",
    "Unknown status filter.": "Filtro de estado desconocido.",
    # input validation
    "JSON body required.": "Se requiere un cuerpo JSON.",
    "Invalid id.": "Identificador no válido.",
    "{key} is required.": "{key} es obligatorio.",
    "{key} must be text.": "{key} debe ser texto.",
    "{key} must be a whole number.": "{key} debe ser un número entero.",
    "{key} must be at least {minimum}.": "{key} debe ser al menos {minimum}.",
    "{key} is too large.": "{key} es demasiado grande.",
    "{key} must be true or false.": "{key} debe ser verdadero o falso.",
    "{key} must be a date like 2026-10-14.": "{key} debe ser una fecha como 2026-10-14.",
    "{key} must be one of: {choices}.": "{key} debe ser uno de: {choices}.",
    # loan terms (schedule.validate_terms)
    "principal must be greater than zero": "el monto debe ser mayor que cero",
    "interest_type must be compound, simple or fixed": "interest_type debe ser compound, simple o fixed",
    "schedule must be weekly, biweekly or monthly": "schedule debe ser weekly, biweekly o monthly",
    "term_periods must be between 1 and 600": "term_periods debe estar entre 1 y 600",
    "rate must be between 0% and 100%": "la tasa debe estar entre 0% y 100%",
    "amount is too large": "el monto es demasiado grande",
    "fixed fee cannot be negative": "el cargo fijo no puede ser negativo",
    "fixed-fee loans do not take a rate": "los préstamos de cargo fijo no llevan tasa",
    "only fixed-fee loans take a fee": "solo los préstamos de cargo fijo llevan un cargo",
    "start date must be between 2000 and 2100": "la fecha de inicio debe estar entre 2000 y 2100",
    "start date is too far in the future": "la fecha de inicio está demasiado lejos en el futuro",
    # generic
    "Something went wrong.": "Algo salió mal.",
}


def language() -> str:
    """'es' when the client prefers Spanish, otherwise 'en'."""
    if not has_request_context():
        return "en"
    header = request.headers.get("Accept-Language", "")
    for part in header.split(","):
        tag = part.split(";")[0].strip().lower()
        if not tag:
            continue
        return "es" if tag.startswith("es") else "en"
    return "en"


def _(message: str, **kwargs) -> str:
    text = ES.get(message, message) if language() == "es" else message
    return text.format(**kwargs) if kwargs else text
