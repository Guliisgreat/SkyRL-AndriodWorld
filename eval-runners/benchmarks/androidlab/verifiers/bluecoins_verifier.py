"""ADB verifiers for Android-Lab Bluecoins tasks (10 operation tasks)."""

from .base import ADBVerifier

BLUECOINS_DB = "/data/data/com.rammigsoftware.bluecoins/databases/bluecoins.fydb"


class BluecoinsVerifierBase(ADBVerifier):
    """Base with Bluecoins DB query helpers.

    Bluecoins stores amounts in micro-units (amount ÷ 1,000,000 = CNY).
    Transaction types: 3=Expense, 4=Income, 5=Transfer.
    """

    AMOUNT_SCALE = 1_000_000  # amounts stored as amount * 1,000,000

    def get_transactions(self, where: str = "") -> list:
        """Get transactions from Bluecoins DB."""
        sql = ("SELECT transactionsTableID, amount, date, transactionTypeID, "
               "categoryID, notes FROM TRANSACTIONSTABLE")
        if where:
            sql += f" WHERE {where}"
        result = self.sqlite_query(BLUECOINS_DB, sql)
        txns = []
        for line in result.strip().split("\n"):
            if line.startswith("transactionsTableID") or not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 6:
                try:
                    txns.append({
                        "id": parts[0],
                        "amount": int(parts[1]) / self.AMOUNT_SCALE,
                        "amount_raw": int(parts[1]),
                        "date": parts[2],
                        "type_id": int(parts[3]) if parts[3].isdigit() else 0,
                        "category_id": parts[4],
                        "notes": parts[5].strip(),
                    })
                except (ValueError, IndexError):
                    continue
        return txns

    def get_latest_transaction(self) -> dict:
        """Get the most recently added transaction."""
        sql = ("SELECT transactionsTableID, amount, date, transactionTypeID, "
               "categoryID, notes FROM TRANSACTIONSTABLE "
               "ORDER BY transactionsTableID DESC LIMIT 1")
        result = self.sqlite_query(BLUECOINS_DB, sql)
        for line in result.strip().split("\n"):
            if line.startswith("transactionsTableID") or not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 6:
                try:
                    return {
                        "id": parts[0],
                        "amount": int(parts[1]) / self.AMOUNT_SCALE,
                        "amount_raw": int(parts[1]),
                        "date": parts[2],
                        "type_id": int(parts[3]) if parts[3].isdigit() else 0,
                        "category_id": parts[4],
                        "notes": parts[5].strip(),
                    }
                except (ValueError, IndexError):
                    pass
        return {}

    def find_transaction_by_date(self, date_fragment: str) -> list:
        """Find transactions matching a date fragment (e.g., '2024-05-15')."""
        return [t for t in self.get_transactions() if date_fragment in t["date"]]


class Bluecoins6_Expense512(BluecoinsVerifierBase):
    """bluecoins_6: Log an expenditure of 512 CNY."""
    task_id = "bluecoins_6"

    def is_successful(self):
        txns = self.get_transactions()
        # Look for new expense of 512
        type_ok = cash_ok = False
        for t in txns:
            if t["type_id"] == 3 and abs(t["amount"]) == 512:
                type_ok = True
                cash_ok = True
                break
            if t["type_id"] == 3 and abs(t["amount"]) in (512.0, 512.00):
                type_ok = True
                cash_ok = True
                break
        return {"complete": type_ok and cash_ok, "1": type_ok, "2": cash_ok}


class Bluecoins7_Income8000_Salary(BluecoinsVerifierBase):
    """bluecoins_7: Record income of 8000 CNY, mark as 'salary'."""
    task_id = "bluecoins_7"

    def is_successful(self):
        txns = self.get_transactions()
        type_ok = cash_ok = note_ok = False
        for t in txns:
            if t["type_id"] == 4 and abs(t["amount"]) == 8000:
                type_ok = True
                cash_ok = True
                if t["notes"].lower() == "salary":
                    note_ok = True
                break
        return {
            "complete": type_ok and cash_ok and note_ok,
            "1": type_ok, "2": cash_ok, "3": note_ok,
        }


class Bluecoins8_Expense768_May11(BluecoinsVerifierBase):
    """bluecoins_8: Note expense of 768 CNY for May 11, 2024."""
    task_id = "bluecoins_8"

    def is_successful(self):
        txns = self.get_transactions()
        type_ok = date_ok = cash_ok = False
        for t in txns:
            if t["type_id"] == 3 and abs(t["amount"]) == 768:
                type_ok = True
                cash_ok = True
                if "2024-05-11" in t["date"] or "May 11" in t["date"]:
                    date_ok = True
                break
        return {
            "complete": type_ok and date_ok and cash_ok,
            "1": type_ok, "2": date_ok, "3": cash_ok,
        }


class Bluecoins9_Income314_Mar8(BluecoinsVerifierBase):
    """bluecoins_9: Income of 3.14 CNY on March 8, 2024, note 'Weixin red packet'."""
    task_id = "bluecoins_9"

    def is_successful(self):
        txns = self.get_transactions()
        type_ok = date_ok = cash_ok = note_ok = False
        for t in txns:
            if t["type_id"] == 4 and abs(t["amount"] - 3.14) < 0.01:
                type_ok = True
                cash_ok = True
                if "2024-03-08" in t["date"] or "March 8" in t["date"] or "2024-3-8" in t["date"]:
                    date_ok = True
                if "weixin red packet" in t["notes"].lower():
                    note_ok = True
                break
        return {
            "complete": type_ok and date_ok and cash_ok and note_ok,
            "1": type_ok, "2": date_ok, "3": cash_ok, "4": note_ok,
        }


class Bluecoins10_Expense256_May14_Eating(BluecoinsVerifierBase):
    """bluecoins_10: Expense 256 CNY on May 14 2024, marked as 'eating'."""
    task_id = "bluecoins_10"

    def is_successful(self):
        txns = self.get_transactions()
        type_ok = date_ok = cash_ok = note_ok = False
        for t in txns:
            if t["type_id"] == 3 and abs(t["amount"]) == 256:
                type_ok = True
                cash_ok = True
                if "2024-05-14" in t["date"]:
                    date_ok = True
                if "eating" in t["notes"].lower():
                    note_ok = True
                break
        return {
            "complete": type_ok and date_ok and cash_ok and note_ok,
            "1": type_ok, "2": date_ok, "3": cash_ok, "4": note_ok,
        }


class Bluecoins11_EditExpenseMay15(BluecoinsVerifierBase):
    """bluecoins_11: Adjust expenditure on May 15 to 500 CNY."""
    task_id = "bluecoins_11"

    def is_successful(self):
        txns = self.find_transaction_by_date("2024-05-15")
        date_ok = cash_ok = False
        for t in txns:
            if "2024-05-15" in t["date"]:
                date_ok = True
                if abs(t["amount"]) == 500:
                    cash_ok = True
                break
        return {"complete": date_ok and cash_ok, "1": date_ok, "2": cash_ok}


class Bluecoins12_ShiftIncomeMay12(BluecoinsVerifierBase):
    """bluecoins_12: Shift income from May 12 to May 10, amount to 18,250 CNY."""
    task_id = "bluecoins_12"

    def is_successful(self):
        txns = self.get_transactions()
        date_ok = cash_ok = False
        for t in txns:
            if t["type_id"] == 4 and abs(t["amount"]) == 18250:
                cash_ok = True
                if "2024-05-10" in t["date"]:
                    date_ok = True
                break
        return {"complete": date_ok and cash_ok, "1": date_ok, "2": cash_ok}


class Bluecoins13_SwitchExpenseToIncome(BluecoinsVerifierBase):
    """bluecoins_13: Switch May 13 from expense to income, add note 'Gift'."""
    task_id = "bluecoins_13"

    def is_successful(self):
        txns = self.find_transaction_by_date("2024-05-13")
        type_ok = date_ok = note_ok = False
        for t in txns:
            if "2024-05-13" in t["date"]:
                date_ok = True
                if t["type_id"] == 4:  # Income
                    type_ok = True
                if "gift" in t["notes"].lower():
                    note_ok = True
                break
        return {
            "complete": type_ok and date_ok and note_ok,
            "1": type_ok, "2": date_ok, "3": note_ok,
        }


class Bluecoins14_SwitchIncomeToExpense(BluecoinsVerifierBase):
    """bluecoins_14: Change May 2 from income to expense, amount 520, note 'Wrong Operation'."""
    task_id = "bluecoins_14"

    def is_successful(self):
        txns = self.find_transaction_by_date("2024-05-02")
        type_ok = date_ok = cash_ok = note_ok = False
        for t in txns:
            if "2024-05-02" in t["date"]:
                date_ok = True
                if t["type_id"] == 3:  # Expense
                    type_ok = True
                if abs(t["amount"]) == 520:
                    cash_ok = True
                if "wrong operation" in t["notes"].lower():
                    note_ok = True
                break
        return {
            "complete": type_ok and date_ok and cash_ok and note_ok,
            "1": type_ok, "2": date_ok, "3": cash_ok, "4": note_ok,
        }


class Bluecoins15_MoveExpenseMay12(BluecoinsVerifierBase):
    """bluecoins_15: Move expense from May 12 to May 13, amount 936.02, note 'Grocery Shopping'."""
    task_id = "bluecoins_15"

    def is_successful(self):
        txns = self.find_transaction_by_date("2024-05-13")
        date_ok = cash_ok = note_ok = False
        for t in txns:
            if "2024-05-13" in t["date"] and t["type_id"] == 3:
                date_ok = True
                if abs(t["amount"] - 936.02) < 0.01:
                    cash_ok = True
                if "grocery shopping" in t["notes"].lower():
                    note_ok = True
                break
        return {
            "complete": date_ok and cash_ok and note_ok,
            "1": date_ok, "2": cash_ok, "3": note_ok,
        }


FUNCTION_MAP = {
    "bluecoins_6": Bluecoins6_Expense512,
    "bluecoins_7": Bluecoins7_Income8000_Salary,
    "bluecoins_8": Bluecoins8_Expense768_May11,
    "bluecoins_9": Bluecoins9_Income314_Mar8,
    "bluecoins_10": Bluecoins10_Expense256_May14_Eating,
    "bluecoins_11": Bluecoins11_EditExpenseMay15,
    "bluecoins_12": Bluecoins12_ShiftIncomeMay12,
    "bluecoins_13": Bluecoins13_SwitchExpenseToIncome,
    "bluecoins_14": Bluecoins14_SwitchIncomeToExpense,
    "bluecoins_15": Bluecoins15_MoveExpenseMay12,
}
