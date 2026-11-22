# Mobile Provider Billing Guide

Version 2.1 — fictitious document prepared for the SE4458 midterm. It describes how
monthly bills are produced for postpaid mobile subscribers. It is a policy document,
not a billing database: live balances and usage always come from the Billing API.

## 1. Scope and Definitions

### 1.1 Who this guide applies to
This guide applies to all postpaid subscribers on the Standard plan. Each subscriber is
identified by a subscriber number (for example 5551001). One subscriber number has one
bill per calendar month.

### 1.2 Units of measure
Phone usage is measured in minutes. Internet (mobile data) usage is measured in megabytes
(MB). For billing purposes 1 GB is defined as 1,000 MB, not 1,024 MB. Amounts are in US
dollars (USD).

### 1.3 Usage recording
Usage is recorded by the network in fixed units: each phone usage event adds 10 minutes
and each internet usage event adds 1 MB to the current month. Usage recorded for a month
always belongs to that month's bill.

## 2. Billing Cycle

### 2.1 Monthly cycle
The billing cycle is one calendar month, from the first day to the last day of the month.
Usage made on the last day of a month is billed in that month, not the next one.

### 2.2 Bill calculation date
Bills are calculated after the cycle closes, normally within the first three days of the
following month. A bill can be recalculated if late usage records arrive; recalculation
never removes payments that were already made.

### 2.3 Due date
The payment due date is the 20th day of the month following the billing cycle. For
example, the October bill is due on 20 November.

## 3. Phone Allowance and Pricing

### 3.1 Included minutes
Every subscriber gets 1,000 free phone minutes per month. Calls within the first 1,000
minutes cost nothing.

### 3.2 Extra minutes
After the free 1,000 minutes, phone usage is charged at $10 for each started block of
1,000 minutes. A started block is charged in full: using 1,001 minutes costs $10 and using
2,001 minutes costs $20.

### 3.3 Phone examples
| Minutes used | Extra blocks | Phone charge |
|---|---|---|
| 800 | 0 | $0 |
| 1,000 | 0 | $0 |
| 1,450 | 1 | $10 |
| 2,300 | 2 | $20 |

## 4. Internet (Mobile Data) Allowance and Pricing

### 4.1 Base data package
The internet package costs a flat $50 per month and includes up to 20 GB (20,000 MB) of
mobile data. The $50 base package fee is charged every month, even if less data is used.

### 4.2 Extra data charges
Data used above the 20 GB allowance is charged as extra internet. Each started additional
block of 10 GB (10,000 MB) costs $10. There is no per-MB price: one extra megabyte above
the allowance starts a new 10 GB block. This is the most common reason for a higher bill.

### 4.3 Internet examples
| Data used | Extra 10 GB blocks | Internet charge |
|---|---|---|
| 15 GB | 0 | $50 |
| 20 GB | 0 | $50 |
| 20.001 GB | 1 | $60 |
| 35 GB | 2 | $70 |
| 41.25 GB | 3 | $80 |

### 4.4 Unused allowance
Unused minutes or data do not roll over to the next month and are not refunded.

## 5. How the Bill Total Is Calculated

### 5.1 Bill formula
Bill total = phone charge + internet charge. With no extra usage the minimum monthly bill
is $50 (internet base package only).

### 5.2 Rounding rules
Extra usage is always rounded up to the next full block (1,000 minutes for phone, 10 GB
for internet). Money amounts are kept with two decimals.

### 5.3 Why a bill can be higher than last month
A bill is higher than the previous month when the subscriber passed the 1,000 free minutes,
passed the 20 GB data allowance, or used more blocks than before. Compare the detailed bill
of both months: the charge breakdown shows the extra minute blocks and extra data blocks.

## 6. Payments

### 6.1 Payment channels
Bills can be paid in the mobile app, through the billing assistant or at partner banks.
Card details are never collected by the assistant; payments in this system are simulated.

### 6.2 Partial payments
Partial payments are accepted. A bill can be paid in several parts until the remaining
balance reaches zero. The bill status is UNPAID before any payment, PARTIALLY_PAID after a
partial payment and PAID when the remaining balance is zero.

### 6.3 Overpayment
A payment larger than the remaining balance is rejected. Pay at most the remaining balance.

### 6.4 Duplicate transactions
Every payment carries a unique transaction ID. A payment with a transaction ID that was
already used is rejected and does not change the balance, so a retried request can not
charge the subscriber twice.

### 6.5 Confirmation before payment
Assistants and apps must show the amount and the bill month and get an explicit
confirmation from the subscriber before submitting a payment.

## 7. Late Payments

### 7.1 Late payment fee
If the bill is not fully paid by the due date, a late payment fee of $5 is applied to the
next bill. The fee is applied once per overdue bill.

### 7.2 Service restriction
If a bill remains unpaid 30 days after the due date, outgoing calls and mobile data may
be restricted until the outstanding balance is paid. Incoming calls and emergency calls
stay available.

### 7.3 Reconnection
Service is restored within 24 hours after the overdue balance is paid in full. No
reconnection fee is charged.

## 8. Billing Disputes

### 8.1 How to dispute a charge
A subscriber who believes a charge is wrong can open a billing dispute within 60 days of
the bill date through customer support. The dispute should include the subscriber number,
bill month and the charge being questioned.

### 8.2 During a dispute
Only the disputed amount is put on hold. The undisputed part of the bill must still be
paid by the due date to avoid late fees.

### 8.3 Dispute outcome
Disputes are answered within 10 business days. If the dispute is accepted, the amount is
credited to the next bill.

## 9. Account Security and Privacy

### 9.1 Identity
Detailed bills, usage records and payments are available only to the signed-in account
holder. Giving another subscriber number in a chat does not grant access to that account.

### 9.2 Public bill summary
The bill summary (total, paid amount, remaining balance and status) can be queried with a
subscriber number and period without signing in, for quick checks from the mobile app.
