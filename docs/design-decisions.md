# Design decisions

**The missing-information check overlaps with the form.** The form and the server already reject a missing name, station, number, or note. We still run the model check because the spec asks for three checks at the same time, and this is the second of them. The check receives every saved field. Its extra value is a note that is present but vague. We are not using it as a second copy of form validation.

**Spam is a label, not a new verdict.** An injected note is separated on the console and still reviewed. The numbers remain the only source of `go` and `no_go`.

**Two seriousness labels.** One is the model’s reading of the note. The other is what the deadline uses after the limit rule is applied.
