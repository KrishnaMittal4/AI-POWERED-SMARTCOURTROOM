"""
Generates a few realistic-looking sample judgment PDFs so you can test
the pipeline immediately, before you've downloaded real judgments.
Replace these with real PDFs in judgments/ later.
"""
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
import textwrap
import os

SAMPLES = [
    {
        "filename": "case1_cheque_bounce.pdf",
        "text": """IN THE HIGH COURT OF DELHI
CRL. M.C. 1234/2019

Ramesh Kumar ... Petitioner
Versus
Suresh Traders ... Respondent

CORAM: HON'BLE MR. JUSTICE A.K. SHARMA

JUDGMENT

1. This petition has been filed under Section 482 of the Code of
Criminal Procedure seeking quashing of proceedings under Section 138
of the Negotiable Instruments Act, 1881.

2. FACTS: The complainant advanced a loan of Rs. 5,00,000 to the
accused. In discharge of the said liability, the accused issued a
cheque dated 12.03.2018 which, upon presentation, was returned
unpaid with the remark "insufficient funds".

3. ISSUE: Whether the prosecution has been able to establish that
the cheque was issued towards a legally enforceable debt or other
liability.

4. It is a settled principle that once the cheque and the demand
notice are proved, a presumption arises under Section 139 of the
Act that the cheque was issued for discharge of a legally
enforceable debt. The burden then shifts to the accused to rebut
this presumption.

5. In the present case, the accused has failed to lead any credible
evidence to rebut the statutory presumption. The mere denial of
liability, without more, is insufficient to displace the
presumption under Section 139.

6. The prosecution failed to establish that the notice was served
within the statutory period in respect of one of the two cheques,
and to that limited extent the proceedings qua that cheque are
quashed. The proceedings in respect of the remaining cheque shall
continue.

7. ORDER: The petition is partly allowed. Proceedings in CC No.
456/2018 qua cheque no. 2 are quashed. Proceedings qua cheque no. 1
shall continue before the Trial Court.
""",
    },
    {
        "filename": "case2_acquittal_evidence.pdf",
        "text": """IN THE HIGH COURT OF BOMBAY
CRIMINAL APPEAL NO. 987 OF 2017

State of Maharashtra ... Appellant
Versus
Vijay Patil ... Respondent

CORAM: HON'BLE MR. JUSTICE R.N. DESHMUKH

JUDGMENT

1. This appeal challenges the order of acquittal passed by the
Trial Court in Sessions Case No. 45/2015, whereby the respondent
was acquitted of charges under Section 302 of the Indian Penal
Code.

2. FACTS: The prosecution case rested primarily on circumstantial
evidence and the testimony of two eyewitnesses, both of whom turned
hostile during trial.

3. ISSUE: Whether the prosecution has proved the guilt of the
accused beyond reasonable doubt on the basis of the circumstantial
evidence on record.

4. It is well established that in cases resting on circumstantial
evidence, the chain of circumstances must be complete and must
exclude every hypothesis other than the guilt of the accused. Even
a single missing link can be fatal to the prosecution's case.

5. In the present matter, the prosecution failed to establish the
case beyond reasonable doubt. The recovery of the weapon was not
proved in accordance with law, and the medical evidence did not
conclusively connect the accused to the crime.

6. Mere suspicion, however grave, cannot take the place of proof.
The prosecution failed to establish the case beyond reasonable
doubt, and the accused is entitled to the benefit of the doubt.

7. ORDER: The appeal is dismissed. The order of acquittal passed
by the Trial Court is upheld.
""",
    },
    {
        "filename": "case3_contract_breach.pdf",
        "text": """IN THE HIGH COURT OF MADRAS
C.S. NO. 321 OF 2016

ABC Constructions Pvt. Ltd. ... Plaintiff
Versus
XYZ Developers ... Defendant

CORAM: HON'BLE MS. JUSTICE P. LAKSHMI

JUDGMENT

1. This suit has been filed for specific performance of an
agreement for sale dated 10.01.2015, and in the alternative, for
recovery of damages for breach of contract.

2. FACTS: The plaintiff entered into an agreement to purchase a
commercial property from the defendant for a consideration of Rs.
2,50,00,000. The plaintiff paid an advance of Rs. 50,00,000, but
the defendant failed to execute the sale deed within the agreed
time and subsequently sold the property to a third party.

3. ISSUE: Whether the plaintiff is entitled to specific performance
of the agreement, or in the alternative, to damages for breach of
contract.

4. Time is not ordinarily of the essence in contracts relating to
immovable property unless expressly stipulated. In the present
case, no such stipulation exists in the agreement.

5. However, since the suit property has already been conveyed to a
bona fide third-party purchaser for value without notice, specific
performance cannot be granted against the subsequent purchaser.

6. The plaintiff is nevertheless entitled to damages for breach of
contract, measured as the difference between the contract price and
the market value of the property as on the date of breach, along
with refund of the advance amount with interest.

7. ORDER: The suit is decreed in part. The defendant shall refund
Rs. 50,00,000 with interest at 9% per annum, and pay damages of Rs.
75,00,000 to the plaintiff within eight weeks.
""",
    },
]


def make_pdf(filepath, text):
    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4
    margin = 0.75 * inch
    y = height - margin
    c.setFont("Helvetica", 10)
    for raw_line in text.split("\n"):
        wrapped = textwrap.wrap(raw_line, width=95) or [""]
        for line in wrapped:
            if y < margin:
                c.showPage()
                c.setFont("Helvetica", 10)
                y = height - margin
            c.drawString(margin, y, line)
            y -= 13
    c.save()


if __name__ == "__main__":
    os.makedirs("judgments", exist_ok=True)
    for sample in SAMPLES:
        path = os.path.join("judgments", sample["filename"])
        make_pdf(path, sample["text"])
        print(f"Created {path}")
