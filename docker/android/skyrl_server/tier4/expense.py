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

"""Tier 4 tasks for Pro Expense app - ADB-exclusive."""

import random
import re
import time
from typing import Any

from android_world.env import interface
from android_world.task_evals import task_eval
from android_world.task_evals.utils import sqlite_schema_utils
from android_world.task_evals.utils import sqlite_utils

_DB_PATH = '/data/data/com.arduia.expense/databases/accounting.db'
_TABLE = 'expense'
_APP_NAME = 'pro expense'
_DB_KEY = 'expense_id'

# Category mapping (from sqlite_schema_utils.Expense)
_CATEGORIES = sqlite_schema_utils.Expense.category_id_to_name

# "Travel" doesn't exist in the fixed list; use Transportation (7) as proxy
_CATEGORY_TRAVEL = 7   # Transportation
_CATEGORY_FOOD = 3
_CATEGORY_HOUSING = 4
_CATEGORY_ENTERTAINMENT = 6


def _now_ms() -> int:
  return int(time.time() * 1000)


def _month_start_ms() -> int:
  import datetime
  now = datetime.datetime.utcnow()
  return int(datetime.datetime(now.year, now.month, 1).timestamp() * 1000)


def _last_month_range_ms():
  import datetime
  now = datetime.datetime.utcnow()
  if now.month == 1:
    start = datetime.datetime(now.year - 1, 12, 1)
    end = datetime.datetime(now.year, 1, 1)
  else:
    start = datetime.datetime(now.year, now.month - 1, 1)
    end = datetime.datetime(now.year, now.month, 1)
  return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _insert_expenses(rows: list[sqlite_schema_utils.Expense],
                     env: interface.AsyncEnv) -> None:
  sqlite_utils.insert_rows_to_remote_db(
      rows, _DB_KEY, _TABLE, _DB_PATH, _APP_NAME, env
  )


def _get_expenses(env: interface.AsyncEnv) -> list[sqlite_schema_utils.Expense]:
  return sqlite_utils.get_rows_from_remote_device(
      _TABLE, _DB_PATH, sqlite_schema_utils.Expense, env
  )


def _clear_expenses(env: interface.AsyncEnv) -> None:
  sqlite_utils.delete_all_rows_from_table(_TABLE, _DB_PATH, env, _APP_NAME)


class Tier4BulkRecategorizeExpense(task_eval.TaskEval):
  """Change all expenses with category 'Food' to 'Entertainment'. ADB-exclusive."""

  app_names = (_APP_NAME,)
  complexity = 1.5
  schema = {'type': 'object', 'properties': {}, 'required': []}
  template = (
      "I miscategorized some expenses — change all 'Food' entries in Pro"
      " Expense to 'Entertainment'."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _clear_expenses(env)
    now_ms = _now_ms()
    rows = []
    # 4 Food expenses → should be recategorized
    for i in range(4):
      rows.append(sqlite_schema_utils.Expense(
          name=f'food_item_{i}', amount=random.randint(100, 1000),
          category=_CATEGORY_FOOD, created_date=now_ms, modified_date=now_ms,
      ))
    # 2 Housing expenses → should stay
    for i in range(2):
      rows.append(sqlite_schema_utils.Expense(
          name=f'housing_item_{i}', amount=random.randint(5000, 20000),
          category=_CATEGORY_HOUSING, created_date=now_ms, modified_date=now_ms,
      ))
    _insert_expenses(rows, env)
    self._food_names = [f'food_item_{i}' for i in range(4)]

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _clear_expenses(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    rows = _get_expenses(env)
    for row in rows:
      if row.name in self._food_names and row.category == _CATEGORY_FOOD:
        return 0.0  # Still Food — not changed
    for row in rows:
      if row.name in self._food_names and row.category != _CATEGORY_ENTERTAINMENT:
        return 0.0  # Changed to wrong category
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4FilterExpenseHighTravelLastMonth(task_eval.TaskEval):
  """List expenses >$50, category Transportation, from last month. ADB-exclusive."""

  app_names = (_APP_NAME,)
  complexity = 2.0
  schema = {'type': 'object', 'properties': {}, 'required': []}
  template = (
      "List all Pro Expense records with amount greater than $50, category"
      " 'Transportation', from last month. Output the expense names."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _clear_expenses(env)
    last_start, last_end = _last_month_range_ms()
    now_ms = _now_ms()
    mid_last = (last_start + last_end) // 2
    rows = []
    self._ground_truth: list[str] = []

    # 3 matching: Transportation + >$50 + last month
    for i in range(3):
      name = f'travel_high_{i}'
      rows.append(sqlite_schema_utils.Expense(
          name=name, amount=random.randint(5100, 20000),
          category=_CATEGORY_TRAVEL,
          created_date=mid_last, modified_date=mid_last,
      ))
      self._ground_truth.append(name)

    # Distractors
    rows.append(sqlite_schema_utils.Expense(  # Too cheap
        name='travel_cheap', amount=200, category=_CATEGORY_TRAVEL,
        created_date=mid_last, modified_date=mid_last,
    ))
    rows.append(sqlite_schema_utils.Expense(  # Wrong category
        name='food_high', amount=random.randint(5100, 10000),
        category=_CATEGORY_FOOD, created_date=mid_last, modified_date=mid_last,
    ))
    rows.append(sqlite_schema_utils.Expense(  # This month
        name='travel_thismonth', amount=random.randint(5100, 10000),
        category=_CATEGORY_TRAVEL, created_date=now_ms, modified_date=now_ms,
    ))
    _insert_expenses(rows, env)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _clear_expenses(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    if not self._ground_truth:
      return 0.0
    cache = getattr(env, 'interaction_cache', '') or ''
    for name in self._ground_truth:
      if name not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4AggregationExpenseCategoryTop3(task_eval.TaskEval):
  """Top 3 expense categories by total amount this month. ADB-exclusive."""

  app_names = (_APP_NAME,)
  complexity = 2.0
  schema = {'type': 'object', 'properties': {}, 'required': []}
  template = (
      "What are the top 3 expense categories by total amount this month in"
      " Pro Expense? Output the category names."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _clear_expenses(env)
    month_start = _month_start_ms()
    now_ms = _now_ms()
    mid = (month_start + now_ms) // 2

    # Fixed totals per category (cents): Food=15000, Housing=30000,
    # Entertainment=10000, Transportation=25000, Health Care=5000
    category_amounts = {
        _CATEGORY_FOOD: [3000, 5000, 7000],          # total 15000
        _CATEGORY_HOUSING: [10000, 12000, 8000],      # total 30000
        _CATEGORY_ENTERTAINMENT: [3000, 3500, 3500],  # total 10000
        _CATEGORY_TRAVEL: [10000, 8000, 7000],        # total 25000
        9: [2000, 1500, 1500],                        # Health Care: 5000
    }
    rows = []
    for cat, amounts in category_amounts.items():
      for i, amt in enumerate(amounts):
        rows.append(sqlite_schema_utils.Expense(
            name=f'exp_{cat}_{i}', amount=amt, category=cat,
            created_date=mid, modified_date=mid,
        ))
    _insert_expenses(rows, env)
    # Top 3 by total: Housing(30000) > Transportation(25000) > Food(15000)
    self._ground_truth: list[str] = ['Housing', 'Transportation', 'Food']

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _clear_expenses(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    if not self._ground_truth:
      return 0.0
    cache = getattr(env, 'interaction_cache', '') or ''
    for name in self._ground_truth:
      if name.lower() not in cache.lower():
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4AggregationExpenseSuspectedDuplicates(task_eval.TaskEval):
  """Count suspected duplicate expenses (same date, amount, category). ADB-exclusive."""

  app_names = (_APP_NAME,)
  complexity = 1.5
  schema = {'type': 'object', 'properties': {}, 'required': []}
  template = (
      "How many suspected duplicate expenses are there in Pro Expense (same"
      " date, same amount, same category)? Output the number of duplicates"
      " (i.e., extras beyond the first of each group)."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _clear_expenses(env)
    now_ms = _now_ms()
    rows = []
    # 3 duplicate pairs (each pair = 2 rows, so 3 duplicates)
    dup_configs = [
        (500, _CATEGORY_FOOD),
        (1200, _CATEGORY_HOUSING),
        (800, _CATEGORY_ENTERTAINMENT),
    ]
    for amt, cat in dup_configs:
      for _ in range(2):
        rows.append(sqlite_schema_utils.Expense(
            name='dup_expense', amount=amt, category=cat,
            created_date=now_ms, modified_date=now_ms,
        ))
    # 3 unique expenses
    for i in range(3):
      rows.append(sqlite_schema_utils.Expense(
          name=f'unique_{i}', amount=random.randint(100, 400),
          category=random.choice([_CATEGORY_FOOD, _CATEGORY_TRAVEL]),
          created_date=now_ms - i * 86400000, modified_date=now_ms,
      ))
    _insert_expenses(rows, env)
    self._ground_truth: int = 3  # one extra per duplicate pair

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _clear_expenses(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, 'interaction_cache', '') or ''
    return 1.0 if str(self._ground_truth) in cache else 0.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4TopKExpenseHighestAmount(task_eval.TaskEval):
  """List the 5 highest-amount expenses in Pro Expense. ADB-exclusive."""

  app_names = (_APP_NAME,)
  complexity = 1.5
  schema = {'type': 'object', 'properties': {}, 'required': []}
  template = (
      "What are the 5 highest-amount expenses in Pro Expense? List the"
      " expense names and amounts."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _clear_expenses(env)
    now_ms = _now_ms()
    # 10 expenses with known amounts; top 5 are the largest
    amounts = [100, 200, 500, 800, 1200, 2000, 3500, 5000, 8000, 15000]
    random.shuffle(amounts)
    rows = []
    named = []
    for i, amt in enumerate(amounts):
      name = f'expense_amt_{i}'
      rows.append(sqlite_schema_utils.Expense(
          name=name, amount=amt, category=_CATEGORY_FOOD,
          created_date=now_ms, modified_date=now_ms,
      ))
      named.append((name, amt))
    _insert_expenses(rows, env)
    top5 = sorted(named, key=lambda x: x[1], reverse=True)[:5]
    self._ground_truth: list[str] = [n for n, _ in top5]

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _clear_expenses(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    if not self._ground_truth:
      return 0.0
    cache = getattr(env, 'interaction_cache', '') or ''
    for name in self._ground_truth:
      if name not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4CrossAppExpenseToMarkorCalendar(task_eval.TaskEval):
  """Sum this month's expenses, write to Markor + create calendar event. ADB-exclusive."""

  app_names = (_APP_NAME, 'markor', 'simple calendar pro')
  complexity = 2.5
  schema = {'type': 'object', 'properties': {}, 'required': []}
  template = (
      "Calculate the total expenses for this month in Pro Expense, write the"
      " total (in dollars) to a Markor note named 'monthly_summary.md', and"
      " create a Simple Calendar Pro event titled 'Monthly Expense: $<total>'"
      " on the last day of this month."
  )

  _MARKOR_DIR = '/storage/emulated/0/Documents/Markor'
  _CALENDAR_EVENTS_URI = 'content://com.android.calendar/events'
  _NOTE_NAME = 'monthly_summary.md'

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _clear_expenses(env)
    month_start = _month_start_ms()
    now_ms = _now_ms()
    mid = (month_start + now_ms) // 2

    amounts = [1000, 2500, 500, 3000, 750]  # total = 7750 cents = $77.50
    rows = []
    for i, amt in enumerate(amounts):
      rows.append(sqlite_schema_utils.Expense(
          name=f'monthly_exp_{i}', amount=amt, category=_CATEGORY_FOOD,
          created_date=mid, modified_date=mid,
      ))
    _insert_expenses(rows, env)
    total_cents = sum(amounts)
    self._ground_truth_dollars: str = f'{total_cents / 100:.2f}'
    self._note_path = f'{self._MARKOR_DIR}/{self._NOTE_NAME}'

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _clear_expenses(env)
    from android_world.env import adb_utils
    adb_utils.issue_generic_request(
        ['shell', 'rm', '-f', self._note_path], env.controller
    )
    from android_world.env import adb_utils as _adb
    _adb.issue_generic_request(
        ['shell', 'content', 'delete', '--uri', self._CALENDAR_EVENTS_URI,
         '--where', f"title LIKE 'Monthly Expense%'"],
        env.controller,
    )
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    from android_world.env import adb_utils
    # Check Markor note
    res = adb_utils.issue_generic_request(
        ['shell', 'cat', self._note_path], env.controller
    )
    note_content = res.generic.output.decode()
    if self._ground_truth_dollars not in note_content:
      return 0.0
    # Check calendar event
    res = adb_utils.issue_generic_request(
        ['shell', 'content', 'query', '--uri', self._CALENDAR_EVENTS_URI,
         '--projection', 'title'],
        env.controller,
    )
    cal_output = res.generic.output.decode()
    if self._ground_truth_dollars not in cal_output:
      return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}




# [EXCLUDED] Removed from Tier 4 benchmark — not registered.
# class Tier4AggregationExpenseAvgPerCategory(task_eval.TaskEval):
#   """Average expense amount per category this month. ADB-exclusive (computed value)."""
#
#   app_names = (_APP_NAME,)
#   complexity = 2.0
#   schema = {'type': 'object', 'properties': {}, 'required': []}
#   template = (
#       "What is the average expense amount (in dollars) per category this month"
#       " in Pro Expense? Output each category and its average."
#   )
#
#   def initialize_task(self, env: interface.AsyncEnv) -> None:
#     super().initialize_task(env)
#     _clear_expenses(env)
#     month_start = _month_start_ms()
#     now_ms = _now_ms()
#     mid = (month_start + now_ms) // 2
#
#     # Food: 3 expenses → avg = 2000/3 ≈ 667 cents = $6.67
#     # Housing: 2 expenses → avg = 5000/2 = 2500 cents = $25.00
#     category_amounts = {
#         _CATEGORY_FOOD: [500, 700, 800],        # total 2000, avg 667
#         _CATEGORY_HOUSING: [2000, 3000],          # total 5000, avg 2500
#         _CATEGORY_ENTERTAINMENT: [300, 400, 500], # total 1200, avg 400
#     }
#     rows = []
#     for cat, amounts in category_amounts.items():
#       for i, amt in enumerate(amounts):
#         rows.append(sqlite_schema_utils.Expense(
#             name=f'avgcat_{cat}_{i}', amount=amt, category=cat,
#             created_date=mid, modified_date=mid,
#         ))
#     _insert_expenses(rows, env)
#     # Ground truth: category with highest average is Housing ($25.00)
#     self._ground_truth_highest: str = 'Housing'
#     self._ground_truth_avg: str = '25.00'
#
#   def tear_down(self, env: interface.AsyncEnv) -> None:
#     _clear_expenses(env)
#     super().tear_down(env)
#
#   def is_successful(self, env: interface.AsyncEnv) -> float:
#     super().is_successful(env)
#     cache = (getattr(env, 'interaction_cache', '') or '').lower()
#     if 'housing' not in cache:
#       return 0.0
#     if 'food' not in cache:
#       return 0.0
#     return 1.0
#
#   @classmethod
#   def generate_random_params(cls) -> dict[str, Any]:
#     return {}




class Tier4FilterExpenseAboveAverage(task_eval.TaskEval):
  """List expenses above the overall average. ADB-exclusive (computed threshold)."""

  app_names = (_APP_NAME,)
  complexity = 1.5
  schema = {'type': 'object', 'properties': {}, 'required': []}
  template = (
      "Which of my expenses are above my average spending? List them."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _clear_expenses(env)
    now_ms = _now_ms()
    # Amounts: 100, 200, 500, 1000, 3000 → avg = 960
    amounts = [100, 200, 500, 1000, 3000]
    avg = sum(amounts) / len(amounts)  # 960
    rows = []
    self._ground_truth: list[str] = []
    for i, amt in enumerate(amounts):
      name = f'aboveavg_{i}'
      rows.append(sqlite_schema_utils.Expense(
          name=name, amount=amt, category=_CATEGORY_FOOD,
          created_date=now_ms, modified_date=now_ms,
      ))
      if amt > avg:
        self._ground_truth.append(name)
    _insert_expenses(rows, env)
    # Above avg: 1000, 3000 → aboveavg_3, aboveavg_4

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _clear_expenses(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, 'interaction_cache', '') or ''
    for name in self._ground_truth:
      if name not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}




# [EXCLUDED] Removed from Tier 4 benchmark — not registered.
# class Tier4TopKExpenseDaysMostSpent(task_eval.TaskEval):
#   """3 days with highest total spending this month. ADB-exclusive."""
#
#   app_names = (_APP_NAME,)
#   complexity = 2.0
#   schema = {'type': 'object', 'properties': {}, 'required': []}
#   template = (
#       "What are the 3 days this month with the highest total spending in"
#       " Pro Expense? Output the dates."
#   )
#
#   def initialize_task(self, env: interface.AsyncEnv) -> None:
#     super().initialize_task(env)
#     _clear_expenses(env)
#     import datetime
#     now = datetime.datetime.utcnow()
#     month_start = _month_start_ms()
#     rows = []
#     # Day 3: 3 expenses totaling 5000
#     # Day 7: 2 expenses totaling 8000
#     # Day 12: 4 expenses totaling 3000
#     # Day 1: 1 expense totaling 10000
#     # Day 9: 2 expenses totaling 2000
#     day_configs = {
#         3: [1000, 2000, 2000],
#         7: [3000, 5000],
#         12: [500, 800, 700, 1000],
#         1: [10000],
#         9: [1000, 1000],
#     }
#     for day, amounts in day_configs.items():
#       day_ms = month_start + (day - 1) * 86400000 + 43200000  # noon
#       for i, amt in enumerate(amounts):
#         rows.append(sqlite_schema_utils.Expense(
#             name=f'dayspend_{day}_{i}', amount=amt,
#             category=_CATEGORY_FOOD, created_date=day_ms, modified_date=day_ms,
#         ))
#     _insert_expenses(rows, env)
#     # Top 3 by total: Day 1 (10000) > Day 7 (8000) > Day 3 (5000)
#     self._ground_truth_days: list[str] = [
#         f"{now.year}-{now.month:02d}-01",
#         f"{now.year}-{now.month:02d}-07",
#         f"{now.year}-{now.month:02d}-03",
#     ]
#
#   def tear_down(self, env: interface.AsyncEnv) -> None:
#     _clear_expenses(env)
#     super().tear_down(env)
#
#   def is_successful(self, env: interface.AsyncEnv) -> float:
#     super().is_successful(env)
#     cache = getattr(env, 'interaction_cache', '') or ''
#     # Accept partial date matches (day numbers)
#     matches = 0
#     for date_str in self._ground_truth_days:
#       if date_str in cache:
#         matches += 1
#       else:
#         # Also accept just the day number
#         day = date_str.split("-")[-1]
#         if day in cache:
#           matches += 1
#     return 1.0 if matches >= 3 else 0.0
#
#   @classmethod
#   def generate_random_params(cls) -> dict[str, Any]:
#     return {}




class Tier4AggregationExpenseAllCategorized(task_eval.TaskEval):
  """Verify all expenses have a valid category. ADB-exclusive (completeness check)."""

  app_names = (_APP_NAME,)
  complexity = 1.2
  schema = {
      'type': 'object',
      'properties': {'variant': {'type': 'string', 'enum': ['all_valid', 'has_uncategorized']}},
      'required': ['variant'],
  }
  template = (
      "Verify that all expenses in Pro Expense have a valid category assigned."
      " If any are uncategorized (category 0 or missing), output their names."
      " If all are categorized, output 'all categorized'."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _clear_expenses(env)
    now_ms = _now_ms()
    rows = []
    # 3 properly categorized expenses
    for i in range(3):
      rows.append(sqlite_schema_utils.Expense(
          name=f'cat_ok_{i}', amount=random.randint(100, 1000),
          category=_CATEGORY_FOOD, created_date=now_ms, modified_date=now_ms,
      ))
    variant = self.params.get('variant', 'has_uncategorized')
    self._uncategorized_names: list[str] = []
    if variant == 'has_uncategorized':
      for i in range(2):
        name = f'cat_missing_{i}'
        rows.append(sqlite_schema_utils.Expense(
            name=name, amount=random.randint(100, 1000),
            category=0,  # uncategorized
            created_date=now_ms, modified_date=now_ms,
        ))
        self._uncategorized_names.append(name)
    _insert_expenses(rows, env)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _clear_expenses(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = (getattr(env, 'interaction_cache', '') or '').lower()
    if not self._uncategorized_names:
      return 1.0 if 'all categorized' in cache else 0.0
    for name in self._uncategorized_names:
      if name not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {'variant': random.choice(['all_valid', 'has_uncategorized'])}




class Tier4BulkDeleteSmallExpenses(task_eval.TaskEval):
  """Delete all expenses below $1 (100 cents). ADB-exclusive."""

  app_names = (_APP_NAME,)
  complexity = 1.5
  schema = {'type': 'object', 'properties': {}, 'required': []}
  template = (
      "Delete all expenses in Pro Expense that are less than $1.00"
      " (less than 100 cents)."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _clear_expenses(env)
    now_ms = _now_ms()
    rows = []
    self._small_names: list[str] = []
    self._keep_names: list[str] = []
    # 3 small expenses (<100 cents)
    for i in range(3):
      name = f'tiny_{i}'
      rows.append(sqlite_schema_utils.Expense(
          name=name, amount=random.randint(10, 90),
          category=_CATEGORY_FOOD, created_date=now_ms, modified_date=now_ms,
      ))
      self._small_names.append(name)
    # 3 normal expenses (>=100 cents)
    for i in range(3):
      name = f'normal_{i}'
      rows.append(sqlite_schema_utils.Expense(
          name=name, amount=random.randint(100, 5000),
          category=_CATEGORY_FOOD, created_date=now_ms, modified_date=now_ms,
      ))
      self._keep_names.append(name)
    _insert_expenses(rows, env)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _clear_expenses(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    rows = _get_expenses(env)
    names = [r.name for r in rows]
    for name in self._small_names:
      if name in names:
        return 0.0
    for name in self._keep_names:
      if name not in names:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}
