"""
Database Schemas for HR & Payroll (Kenya)

Each Pydantic model corresponds to a MongoDB collection (lowercased class name).
This system covers: employees, job groups, loans, leaves, payroll runs, payslips,
and country-specific settings for PAYE, NHIF, NSSF (tailored for Kenya).
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Literal
from datetime import date

# Core HR
class Employee(BaseModel):
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    id_number: Optional[str] = Field(None, description="National ID")
    kra_pin: Optional[str] = Field(None, description="KRA PIN")
    nhif_no: Optional[str] = None
    nssf_no: Optional[str] = None
    department: Optional[str] = None
    job_group_id: Optional[str] = Field(None, description="Reference to jobgroup _id (string)")
    basic_salary: float = Field(0, ge=0)
    allowances: Dict[str, float] = Field(default_factory=dict, description="Named allowances e.g. house, commuter")
    deductions: Dict[str, float] = Field(default_factory=dict, description="Named fixed deductions")
    hire_date: Optional[date] = None
    is_active: bool = True

class Jobgroup(BaseModel):
    code: str
    title: str
    base_salary: float = Field(0, ge=0)
    house_allowance: float = Field(0, ge=0)
    commuter_allowance: float = Field(0, ge=0)
    description: Optional[str] = None

# Loans & Leave
class Loan(BaseModel):
    employee_id: str
    principal: float = Field(..., ge=0)
    interest_rate: float = Field(0.0, ge=0, description="Annual interest rate %")
    term_months: int = Field(..., gt=0)
    start_date: date
    monthly_deduction: Optional[float] = Field(None, ge=0)
    balance: Optional[float] = Field(None, ge=0)
    status: Literal["active", "completed", "defaulted"] = "active"

class Leave(BaseModel):
    employee_id: str
    leave_type: Literal["annual", "sick", "maternity", "paternity", "unpaid", "other"] = "annual"
    start_date: date
    end_date: date
    status: Literal["pending", "approved", "rejected", "taken"] = "pending"
    notes: Optional[str] = None

# Payroll
class PayrollRun(BaseModel):
    period_type: Literal["daily", "weekly", "monthly", "yearly"] = "monthly"
    period_start: date
    period_end: date
    status: Literal["draft", "finalized"] = "draft"
    notes: Optional[str] = None

class Payslip(BaseModel):
    employee_id: str
    payroll_run_id: str
    period_type: Literal["daily", "weekly", "monthly", "yearly"]
    period_start: date
    period_end: date
    basic_salary: float
    allowances: Dict[str, float]
    gross_pay: float
    taxable_pay: float
    paye: float
    nhif: float
    nssf: float
    other_deductions: Dict[str, float]
    loan_deduction: float
    total_deductions: float
    net_pay: float

# Kenya settings
class TaxBand(BaseModel):
    upto: Optional[float] = Field(None, description="Upper limit of band, None for no cap")
    rate: float = Field(..., ge=0, le=1, description="Rate as fraction e.g. 0.1 for 10%")

class NHIFRow(BaseModel):
    min: float
    max: Optional[float] = None
    amount: float

class KenyaSettings(BaseModel):
    currency: str = "KES"
    personal_relief_monthly: float = 2400.0
    paye_bands_monthly: List[TaxBand] = Field(
        default_factory=lambda: [
            TaxBand(upto=24000, rate=0.10),
            TaxBand(upto=32333, rate=0.25),
            TaxBand(upto=500000, rate=0.30),
            TaxBand(upto=800000, rate=0.325),
            TaxBand(upto=None, rate=0.35),
        ]
    )
    nhif_table: List[NHIFRow] = Field(
        default_factory=lambda: [
            NHIFRow(min=0, max=5999, amount=150),
            NHIFRow(min=6000, max=7999, amount=300),
            NHIFRow(min=8000, max=11999, amount=400),
            NHIFRow(min=12000, max=14999, amount=500),
            NHIFRow(min=15000, max=19999, amount=600),
            NHIFRow(min=20000, max=24999, amount=750),
            NHIFRow(min=25000, max=29999, amount=850),
            NHIFRow(min=30000, max=34999, amount=900),
            NHIFRow(min=35000, max=39999, amount=950),
            NHIFRow(min=40000, max=44999, amount=1000),
            NHIFRow(min=45000, max=49999, amount=1100),
            NHIFRow(min=50000, max=59999, amount=1200),
            NHIFRow(min=60000, max=69999, amount=1300),
            NHIFRow(min=70000, max=79999, amount=1400),
            NHIFRow(min=80000, max=89999, amount=1500),
            NHIFRow(min=90000, max=99999, amount=1600),
            NHIFRow(min=100000, max=None, amount=1700),
        ]
    )
    nssf_employee_rate: float = 0.06
    nssf_employee_cap_monthly: float = 2160.0  # Approx Tier I+II cap (update via settings if needed)

# Admin theme/settings
class Theme(BaseModel):
    appearance: Literal["system", "light", "dark"] = "system"
    primary_color: str = "blue"
    accent_color: str = "slate"
