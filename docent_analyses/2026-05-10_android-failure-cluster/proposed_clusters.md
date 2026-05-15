# Proposed Free-Form Clusters (9)

## harness_command_interface_mismatch

**Description:** The agent assumes it can use ordinary adb-shell or Unix commands, but the harness rejects the command tokens themselves as invalid verbs. It keeps retrying the same class of commands instead of realizing the execution interface is the blocker.

**Signature:** Every turn is another `pm`/`cmd`/`ls`/`echo` probe that comes back `not a recognized verb`, and the agent never reaches app data.


## shell_construction_breakage

**Description:** The agent has a plausible path, but it keeps breaking the actual command string: bad quoting, embedded newlines, unsupported flags, malformed projections, or broken arithmetic/SQL. The failure is in command assembly, not in choosing the general surface.

**Signature:** The transcript is full of `no closing quote`, `unexpected '('`, `Invalid column`, or `--limit` errors while the agent repeatedly edits one giant shell one-liner.


## wrong_surface_or_storage_path

**Description:** The agent writes to or queries a backend that the app will not actually consume, such as a private database, shared folder, or generic provider, and then assumes that mutation is enough. The core mistake is choosing the wrong persistence/read surface.

**Signature:** It inserts into SQLite or drops a file in shared storage, but verification through the app/provider never reflects the change.


## permission_or_api_wall_persistence

**Description:** The agent reaches an explicit permission, debuggability, or API wall and then keeps probing neighboring URIs or methods on the same blocked surface instead of pivoting. The pattern is stubborn persistence after a clear denial like `run-as` failure or unsupported provider writes.

**Signature:** After `package not debuggable`, `UnsupportedOperationException`, or `Only sync adapters may write`, the agent just keeps trying similar URIs or methods on that same surface.


## low_level_ipc_guessing

**Description:** The agent drops to binder/service-call hacking and starts guessing transaction codes or shell app-op sequences for clipboard/SMS-style IPC without first confirming the correct API contract. It is not merely blocked; it is probing the wrong low-level protocol shape.

**Signature:** Repeated `service call isms ...` or `service call clipboard ...` attempts end in Parcel/security errors, but the agent keeps varying transaction codes anyway.


## schema_mapping_guessing

**Description:** The agent reverse-engineers hidden numeric or textual mappings from sparse database/APK evidence and then invents IDs, labels, or field semantics from pattern matching. The failure is overconfident schema inference, not just a bad write surface.

**Signature:** It infers values like `category 13`, `importance = 3`, or a table-field meaning from a few rows or resource strings and writes them as if they were verified.


## speculative_value_fabrication

**Description:** The agent invents concrete task data—timestamps, coordinates, note bodies, message text, track waypoints, filenames, or record contents—instead of extracting it from the source material. The core error is grounding-free value creation.

**Signature:** The write contains hard-coded dates, GPS coordinates, or message bodies that were never grounded in the transcript’s source data.


## premature_negative_conclusion

**Description:** The agent treats an empty or partial query result as definitive and stops early, often returning `None` or a raw dump before isolating the requested subset. The failure is concluding from insufficient evidence rather than continuing the extraction path.

**Signature:** A single `No result found` or truncated provider dump leads directly to `None`, even though the requested rows or titles were never fully filtered.


## finalization_or_output_contract_violation

**Description:** The agent has done the work or nearly done it, but loses at the end by violating the run protocol or output contract: malformed `finish`, combining multiple actions into one turn, or emitting the wrong completion format. The task state may be correct, but the run still fails because finalization was invalid.

**Signature:** The data change succeeds, but the final turn fails because `finish` is malformed, paired with another command, or sent in the wrong format.

