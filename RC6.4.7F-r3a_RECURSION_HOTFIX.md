# RC6.4.7F-r3a Recursion Hotfix

Fixed `_set_truth_pending_reference()` so it assigns `self._truth_dashboard_pending_analysis = analysis` instead of recursively calling itself. Added an AST regression test that fails if the setter contains a self-call or lacks the assignment. Decision Engine unchanged.
