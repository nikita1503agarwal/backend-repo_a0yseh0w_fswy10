import os
from datetime import date, datetime
from typing import List, Optional, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document, get_documents
from schemas import Employee, Jobgroup, Loan, Leave, PayrollRun, Payslip, KenyaSettings

app = FastAPI(title="HR & Payroll - Kenya")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Utility: Kenya statutory calculations
settings_cache: Optional[KenyaSettings] = None

def get_settings() -> KenyaSettings:
    global settings_cache
    if settings_cache is None:
        settings_cache = KenyaSettings()
    return settings_cache


def compute_paye_monthly(taxable_pay: float) -> float:
    s = get_settings()
    remaining = taxable_pay
    tax = 0.0
    last_cap = 0.0
    for band in s.paye_bands_monthly:
        cap = band.upto if band.upto is not None else remaining + last_cap
        span = min(remaining, cap - last_cap)
        if span <= 0:
            break
        tax += span * band.rate
        remaining -= span
        last_cap = cap
        if remaining <= 0:
            break
    tax -= s.personal_relief_monthly
    return max(0.0, round(tax, 2))


def compute_nhif(gross_pay: float) -> float:
    s = get_settings()
    for row in s.nhif_table:
        if (gross_pay >= row.min) and (row.max is None or gross_pay <= row.max):
            return float(row.amount)
    return 0.0


def compute_nssf(gross_pay: float) -> float:
    s = get_settings()
    return float(min(gross_pay * s.nssf_employee_rate, s.nssf_employee_cap_monthly))


# CRUD helpers
def insert(model_name: str, payload: BaseModel | Dict) -> str:
    data = payload if isinstance(payload, dict) else payload.model_dump()
    return create_document(model_name.lower(), data)


def list_docs(model_name: str, filter_dict: Dict | None = None, limit: int | None = None):
    return get_documents(model_name.lower(), filter_dict or {}, limit)


# Public endpoints
@app.get("/")
def root():
    return {"message": "HR & Payroll API (Kenya)", "currency": "KES"}


# Employees
@app.post("/employees")
def create_employee(emp: Employee):
    return {"id": insert("employee", emp)}


@app.get("/employees")
def get_employees():
    return list_docs("employee")


# Job groups
@app.post("/jobgroups")
def create_jobgroup(jg: Jobgroup):
    return {"id": insert("jobgroup", jg)}


@app.get("/jobgroups")
def get_jobgroups():
    return list_docs("jobgroup")


# Loans
@app.post("/loans")
def create_loan(loan: Loan):
    # Pre-calc monthly deduction if not provided
    if loan.monthly_deduction is None:
        # Simple amortization approx (interest ignored for simplicity baseline)
        loan.monthly_deduction = round(loan.principal / loan.term_months, 2)
    if loan.balance is None:
        loan.balance = loan.principal
    return {"id": insert("loan", loan)}


@app.get("/loans")
def get_loans():
    return list_docs("loan")


# Leave
@app.post("/leaves")
def create_leave(l: Leave):
    return {"id": insert("leave", l)}


@app.get("/leaves")
def get_leaves():
    return list_docs("leave")


# Payroll calculations
class PayrollPreviewRequest(BaseModel):
    employee_id: str
    period_type: str  # daily, weekly, monthly, yearly
    period_start: date
    period_end: date


@app.post("/payroll/preview")
def payroll_preview(req: PayrollPreviewRequest):
    # Fetch employee
    employees = list_docs("employee", {"_id": {"$exists": True}})
    emp = None
    for e in employees:
        if str(e.get("_id")) == req.employee_id:
            emp = e
            break
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Base salary allocation per period
    basic = float(emp.get("basic_salary", 0))
    if req.period_type == "daily":
        basic = round(basic / 30.0, 2)
    elif req.period_type == "weekly":
        basic = round(basic * 12 / 52, 2)
    elif req.period_type == "monthly":
        basic = basic
    elif req.period_type == "yearly":
        basic = round(basic * 12, 2)
    else:
        raise HTTPException(400, "Invalid period type")

    allowances = emp.get("allowances", {})
    other_deds = emp.get("deductions", {})

    gross = basic + sum(allowances.values())

    # Statutory deductions (for PAYE/NHIF/NSSF we use monthly equivalent baseline)
    monthly_equiv = basic if req.period_type == "monthly" else (gross if req.period_type == "monthly" else emp.get("basic_salary", 0) + sum(allowances.values()))
    paye = compute_paye_monthly(max(0.0, monthly_equiv))
    nhif = compute_nhif(max(0.0, monthly_equiv))
    nssf = compute_nssf(max(0.0, monthly_equiv))

    # Scale statutory to the period when not monthly (simple proportion)
    if req.period_type == "weekly":
        paye = round(paye / 4.333, 2)
        nhif = round(nhif / 4.333, 2)
        nssf = round(nssf / 4.333, 2)
    elif req.period_type == "daily":
        paye = round(paye / 30.0, 2)
        nhif = round(nhif / 30.0, 2)
        nssf = round(nssf / 30.0, 2)
    elif req.period_type == "yearly":
        paye = round(paye * 12, 2)
        nhif = round(nhif * 12, 2)
        nssf = round(nssf * 12, 2)

    loan_deduction = 0.0
    # Active loans for employee
    loans = list_docs("loan", {"employee_id": req.employee_id, "status": "active"})
    for l in loans:
        loan_deduction += float(l.get("monthly_deduction", 0))
        # Scale by period
    if req.period_type == "weekly":
        loan_deduction = round(loan_deduction / 4.333, 2)
    elif req.period_type == "daily":
        loan_deduction = round(loan_deduction / 30.0, 2)
    elif req.period_type == "yearly":
        loan_deduction = round(loan_deduction * 12, 2)

    other_ded_total = sum(other_deds.values())
    total_deductions = round(paye + nhif + nssf + loan_deduction + other_ded_total, 2)
    net = round(gross - total_deductions, 2)

    return {
        "currency": "KES",
        "period_type": req.period_type,
        "period_start": str(req.period_start),
        "period_end": str(req.period_end),
        "basic_salary": round(basic, 2),
        "allowances": allowances,
        "gross_pay": round(gross, 2),
        "taxable_pay": round(max(0.0, gross), 2),
        "paye": paye,
        "nhif": nhif,
        "nssf": nssf,
        "loan_deduction": loan_deduction,
        "other_deductions": other_deds,
        "total_deductions": total_deductions,
        "net_pay": net,
    }


class FinalizePayrollRequest(BaseModel):
    period_type: str
    period_start: date
    period_end: date
    employee_ids: List[str]


@app.post("/payroll/finalize")
def finalize_payroll(req: FinalizePayrollRequest):
    run_id = insert("payrollrun", PayrollRun(
        period_type=req.period_type,
        period_start=req.period_start,
        period_end=req.period_end,
        status="finalized"
    ))

    payslips: List[Dict] = []
    # Build for each employee
    for emp_id in req.employee_ids:
        preview = payroll_preview(PayrollPreviewRequest(
            employee_id=emp_id,
            period_type=req.period_type,
            period_start=req.period_start,
            period_end=req.period_end,
        ))
        slip = Payslip(
            employee_id=emp_id,
            payroll_run_id=run_id,
            period_type=req.period_type,
            period_start=req.period_start,
            period_end=req.period_end,
            basic_salary=preview["basic_salary"],
            allowances=preview["allowances"],
            gross_pay=preview["gross_pay"],
            taxable_pay=preview["taxable_pay"],
            paye=preview["paye"],
            nhif=preview["nhif"],
            nssf=preview["nssf"],
            other_deductions=preview["other_deductions"],
            loan_deduction=preview["loan_deduction"],
            total_deductions=preview["total_deductions"],
            net_pay=preview["net_pay"],
        )
        slip_id = insert("payslip", slip)
        payslips.append({"id": slip_id, **slip.model_dump()})

    return {"run_id": run_id, "currency": "KES", "count": len(payslips), "payslips": payslips}


@app.get("/payslips")
def list_payslips():
    return list_docs("payslip")


@app.get("/schema")
def get_schema_summary():
    # Flames DB viewer can read this to show collections
    return {
        "collections": [
            "employee", "jobgroup", "loan", "leave", "payrollrun", "payslip", "kenyasettings", "theme"
        ]
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
