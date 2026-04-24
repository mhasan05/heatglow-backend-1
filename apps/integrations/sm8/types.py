"""
Typed dataclasses representing ServiceM8 API response shapes.

Reference: https://developer.servicem8.com/reference
These dataclasses model only the fields we actually use. SM8 returns many
more fields per object; ignored fields are simply dropped on deserialisation.
"""
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SM8Company:
    """A customer/company record from ServiceM8."""
    uuid: str
    name: str
    active: int  # 1 = active, 0 = deleted/archived
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postcode: Optional[str] = None
    country: Optional[str] = None
    edit_date: Optional[str] = None  # ISO 8601 timestamp

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> 'SM8Company':
        """Build a SM8Company from raw API JSON, ignoring unknown fields."""
        return cls(
            uuid=data['uuid'],
            name=data.get('name') or 'Unknown',
            active=int(data.get('active', 0)),
            email=data.get('email') or None,
            phone=data.get('phone') or None,
            mobile=data.get('mobile') or None,
            address=data.get('address') or None,
            city=data.get('city') or None,
            state=data.get('state') or None,
            postcode=data.get('postcode') or None,
            country=data.get('country') or None,
            edit_date=data.get('edit_date') or None,
        )


@dataclass
class SM8Job:
    """A job record from ServiceM8."""
    uuid: str
    company_uuid: str           # Links to SM8Company.uuid
    status: str                 # 'Quote', 'Work Order', 'Completed', 'Invoice Sent', 'Paid', etc.
    job_address: Optional[str] = None
    job_description: Optional[str] = None
    job_type: Optional[str] = None
    total_invoice_amount: float = 0.0
    created_date: Optional[str] = None       # YYYY-MM-DD
    completion_date: Optional[str] = None    # YYYY-MM-DD
    quote_date: Optional[str] = None         # YYYY-MM-DD
    active: int = 1
    edit_date: Optional[str] = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> 'SM8Job':
        """Build a SM8Job from raw API JSON."""
        def parse_amount(val: Any) -> float:
            try:
                return float(val or 0)
            except (TypeError, ValueError):
                return 0.0

        return cls(
            uuid=data['uuid'],
            company_uuid=data.get('company_uuid', ''),
            status=data.get('status') or 'Unknown',
            job_address=data.get('job_address') or None,
            job_description=data.get('job_description') or None,
            job_type=data.get('category_name') or None,  # SM8 calls job type 'category_name'
            total_invoice_amount=parse_amount(data.get('total_invoice_amount')),
            created_date=data.get('date') or None,
            completion_date=data.get('completion_date') or None,
            quote_date=data.get('quote_date') or None,
            active=int(data.get('active', 1)),
            edit_date=data.get('edit_date') or None,
        )


@dataclass
class SM8JobMaterial:
    """Material/part used on a job. Used to calculate materials cost."""
    uuid: str
    job_uuid: str
    name: str
    quantity: float = 1.0
    price: float = 0.0

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> 'SM8JobMaterial':
        return cls(
            uuid=data['uuid'],
            job_uuid=data.get('job_uuid', ''),
            name=data.get('name') or '',
            quantity=float(data.get('quantity') or 0),
            price=float(data.get('price') or 0),
        )