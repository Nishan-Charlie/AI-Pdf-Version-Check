Annotation protocol — clause change classification
==================================================

For each row, read the two clause texts and fill in two columns. Do not consult
the system's output; the point of the exercise is an independent judgement.

annotator_change_type — one of:

  Unchanged            The two texts impose the same requirement in the same
                       terms. Differences in spacing, hyphenation, or line
                       breaks introduced by typesetting count as Unchanged.

  Minor Edit           The requirement is the same, but the wording changed:
                       clarification, restructuring, a cross-reference update,
                       or a change of terminology that does not change what a
                       building must do.

  Significant Change   What the building must do is different: a changed
                       measurement, threshold, classification, or scope; a new
                       obligation; a removed exemption.

  Added                The clause exists only in version 2.

  Removed              The clause exists only in version 1.

annotator_alignment_ok — yes / no

  Whether these two clauses are counterparts at all. Answer "no" when the pair
  is mismatched — the system paired two clauses that are about different
  things. Leave blank for Added and Removed rows, which have only one side.

annotator_notes — optional; anything the labels cannot capture. Rows you are
unsure about are worth flagging here, and can be reported separately.

A note on sampling: rows are drawn evenly across the system's predicted
classes so that rare ones (Added, Removed) appear often enough to score. That
makes the sheet's class balance artificial, so report per-class precision and
recall rather than overall accuracy.
