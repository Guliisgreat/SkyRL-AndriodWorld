"""ADB verifiers for Android-Lab Contacts tasks (11 operation tasks)."""

from .base import ADBVerifier


class ContactsVerifierBase(ADBVerifier):
    """Base class with contacts query helpers."""

    CONTACTS_URI = "content://com.android.contacts"

    def get_contact_data(self, display_name: str) -> list:
        """Get all data rows for a contact by display name."""
        result = self.content_query(
            f"{self.CONTACTS_URI}/data",
            projection="raw_contact_id:mimetype:data1:data2:data3",
        )
        rows = self.parse_content_rows(result)
        # Find raw_contact_id(s) for this name
        contact_ids = set()
        for row in rows:
            if (row.get("mimetype") == "vnd.android.cursor.item/name"
                    and row.get("data1", "").strip() == display_name):
                contact_ids.add(row.get("raw_contact_id"))
        # Return all data for those contact IDs
        return [r for r in rows if r.get("raw_contact_id") in contact_ids]

    def contact_exists(self, display_name: str) -> bool:
        return len(self.get_contact_data(display_name)) > 0

    def get_phones(self, data_rows: list) -> list:
        """Extract phone numbers from contact data rows."""
        return [
            r for r in data_rows
            if r.get("mimetype") == "vnd.android.cursor.item/phone_v2"
        ]

    def get_emails(self, data_rows: list) -> list:
        return [
            r for r in data_rows
            if r.get("mimetype") == "vnd.android.cursor.item/email_v2"
        ]

    def get_org(self, data_rows: list) -> str:
        for r in data_rows:
            if r.get("mimetype") == "vnd.android.cursor.item/organization":
                return r.get("data1", "")
        return ""

    def get_birthday(self, data_rows: list) -> str:
        for r in data_rows:
            if r.get("mimetype") == "vnd.android.cursor.item/contact_event":
                if r.get("data2") == "3":  # birthday type
                    return r.get("data1", "")
        return ""

    def get_website(self, data_rows: list) -> str:
        for r in data_rows:
            if r.get("mimetype") == "vnd.android.cursor.item/website":
                return r.get("data1", "")
        return ""


class Contacts1_AddJohn(ContactsVerifierBase):
    """contacts_1: Add John with mobile phone 12345678."""
    task_id = "contacts_1"

    def is_successful(self):
        data = self.get_contact_data("John")
        name_ok = len(data) > 0
        phones = self.get_phones(data)
        phone_ok = any("12345678" in p.get("data1", "") for p in phones)
        return {"complete": name_ok and phone_ok, "1": name_ok, "2": phone_ok}


class Contacts2_AddJohnSmith(ContactsVerifierBase):
    """contacts_2: Add John Smith with phone, email."""
    task_id = "contacts_2"

    def is_successful(self):
        # Check both "John Smith" and just looking for the data
        data = self.get_contact_data("John Smith")
        if not data:
            # Try first name match
            all_data = self.get_contact_data("John")
            data = [r for r in all_data
                    if r.get("data3", "").strip() == "Smith"
                    or "Smith" in r.get("data1", "")]
            if not data:
                data = all_data

        name_ok = len(data) > 0
        phones = self.get_phones(data)
        phone_ok = any("12345678" in p.get("data1", "") for p in phones)
        emails = self.get_emails(data)
        email_ok = any("123456@gmail.com" in e.get("data1", "") for e in emails)
        return {
            "complete": name_ok and phone_ok and email_ok,
            "1": name_ok, "2": phone_ok, "3": email_ok,
        }


class Contacts3_AddXu(ContactsVerifierBase):
    """contacts_3: Add Xu with work phone 12345678 and mobile 87654321."""
    task_id = "contacts_3"

    def is_successful(self):
        data = self.get_contact_data("Xu")
        name_ok = len(data) > 0
        phones = self.get_phones(data)
        work_ok = any("12345678" in p.get("data1", "") for p in phones)
        mobile_ok = any("87654321" in p.get("data1", "") for p in phones)
        return {
            "complete": name_ok and work_ok and mobile_ok,
            "1": name_ok, "2": work_ok, "3": mobile_ok,
        }


class Contacts4_AddChen(ContactsVerifierBase):
    """contacts_4: Add Chen with company Tsinghua University."""
    task_id = "contacts_4"

    def is_successful(self):
        data = self.get_contact_data("Chen")
        name_ok = len(data) > 0
        org = self.get_org(data)
        org_ok = "tsinghua" in org.lower()
        return {"complete": name_ok and org_ok, "1": name_ok, "2": org_ok}


class Contacts5_CreateLabel(ContactsVerifierBase):
    """contacts_5: Create label 'work', add AAA and ABC."""
    task_id = "contacts_5"

    def is_successful(self):
        # Check if group "work" exists with AAA and ABC
        groups = self.content_query(
            "content://com.android.contacts/groups",
            projection="_id:title",
        )
        group_rows = self.parse_content_rows(groups)
        work_group = None
        for g in group_rows:
            if g.get("title", "").lower() == "work":
                work_group = g.get("_id")
                break

        group_ok = work_group is not None
        if not group_ok:
            return {"complete": False, "1": False, "2": False, "3": False}

        # Check membership
        members = self.content_query(
            "content://com.android.contacts/data",
            projection="raw_contact_id:mimetype:data1",
        )
        member_rows = self.parse_content_rows(members)
        # Find group membership entries
        membership_contacts = set()
        for r in member_rows:
            if (r.get("mimetype") == "vnd.android.cursor.item/group_membership"
                    and r.get("data1") == work_group):
                membership_contacts.add(r.get("raw_contact_id"))

        # Check if AAA and ABC are in the group
        aaa_in = self.contact_exists("AAA")
        abc_in = self.contact_exists("ABC")
        members_ok = len(membership_contacts) >= 2

        return {
            "complete": group_ok and members_ok,
            "1": group_ok, "2": aaa_in, "3": abc_in,
        }


class Contacts6_AddWorkPhone(ContactsVerifierBase):
    """contacts_6: Add work phone 00112233 to ABC."""
    task_id = "contacts_6"

    def is_successful(self):
        data = self.get_contact_data("ABC")
        phones = self.get_phones(data)
        # data2=3 means work phone type
        work_phone_ok = any(
            "00112233" in p.get("data1", "") for p in phones
        )
        return {"complete": work_phone_ok, "1": work_phone_ok}


class Contacts7_AddBirthday(ContactsVerifierBase):
    """contacts_7: Add birthday to AAA as 1996/10/24."""
    task_id = "contacts_7"

    def is_successful(self):
        data = self.get_contact_data("AAA")
        bday = self.get_birthday(data)
        ok = "1996" in bday and "10" in bday and "24" in bday
        return {"complete": ok, "1": ok}


class Contacts8_SetWebsite(ContactsVerifierBase):
    """contacts_8: Set ABC's website to abc.github.com."""
    task_id = "contacts_8"

    def is_successful(self):
        data = self.get_contact_data("ABC")
        website = self.get_website(data)
        ok = "abc.github.com" in website
        return {"complete": ok, "1": ok}


class Contacts9_DraftMessage(ContactsVerifierBase):
    """contacts_9: Edit message to ABC 'Nice to meet you', don't send."""
    task_id = "contacts_9"

    def is_successful(self):
        # Check SMS drafts
        result = self.content_query(
            "content://sms/draft",
            projection="address:body",
        )
        rows = self.parse_content_rows(result)
        # Check if there's a draft containing the text
        text_ok = any("Nice to meet you" in r.get("body", "") for r in rows)
        if not text_ok:
            # Fallback: check if messaging app is open with the text
            activity = self.foreground_activity()
            text_ok = "messaging" in activity.lower() or "mms" in activity.lower()
        return {"complete": text_ok, "1": text_ok}


class Contacts10_CallABC(ContactsVerifierBase):
    """contacts_10: Call ABC."""
    task_id = "contacts_10"

    def is_successful(self):
        # Check call log or dialer state
        result = self.content_query(
            "content://call_log/calls",
            projection="number:type:date",
        )
        rows = self.parse_content_rows(result)
        # Check if there's a recent outgoing call
        call_ok = len(rows) > 0
        if not call_ok:
            # Check if dialer/phone is in foreground
            activity = self.foreground_activity()
            call_ok = "dialer" in activity.lower() or "incallui" in activity.lower()
        return {"complete": call_ok, "1": call_ok}


class Contacts11_DeleteAAA(ContactsVerifierBase):
    """contacts_11: Delete contacts AAA."""
    task_id = "contacts_11"

    def is_successful(self):
        ok = not self.contact_exists("AAA")
        return {"complete": ok, "1": ok}


FUNCTION_MAP = {
    "contacts_1": Contacts1_AddJohn,
    "contacts_2": Contacts2_AddJohnSmith,
    "contacts_3": Contacts3_AddXu,
    "contacts_4": Contacts4_AddChen,
    "contacts_5": Contacts5_CreateLabel,
    "contacts_6": Contacts6_AddWorkPhone,
    "contacts_7": Contacts7_AddBirthday,
    "contacts_8": Contacts8_SetWebsite,
    "contacts_9": Contacts9_DraftMessage,
    "contacts_10": Contacts10_CallABC,
    "contacts_11": Contacts11_DeleteAAA,
}
