# Copyright 2025 The android_world Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tier 4: ADB-exclusive tasks.

These tasks are designed for CLI/ADB agents. GUI agents can complete them
only with high cost and error-prone multi-step interactions.
"""

from . import files
from . import sms
from . import system

__all__ = [
    "Tier4BulkDeleteTmpInDownloads",
    "Tier4CoverageNoTmpInDownloads",
    "Tier4HiddenStateListAppVersions",
    "Tier4AggregationCountUnreadSMS",
    "Tier4CrossAppSmsNumbersNotInContacts",
]

Tier4BulkDeleteTmpInDownloads = files.Tier4BulkDeleteTmpInDownloads
Tier4CoverageNoTmpInDownloads = files.Tier4CoverageNoTmpInDownloads
Tier4HiddenStateListAppVersions = system.Tier4HiddenStateListAppVersions
Tier4AggregationCountUnreadSMS = sms.Tier4AggregationCountUnreadSMS
Tier4CrossAppSmsNumbersNotInContacts = sms.Tier4CrossAppSmsNumbersNotInContacts
