package heir

// ToMatchFile converts a catalog template into the type accepted by Stats.SubmitMatch. Fill in the timestamps,
// players and results before submitting. Like a Go struct assignment, slices, maps and pointers are shared.
func (t MatchTemplate) ToMatchFile() HeirMatchFile {
	file := HeirMatchFile{
		EndedAt: t.EndedAt, FixtureID: t.FixtureID, Format: t.Format, Gamemode: t.Gamemode,
		Maps: t.Maps, Note: t.Note, Reference: t.Reference, StartedAt: t.StartedAt, Type: t.Type,
	}
	if t.Rosters != nil {
		file.Rosters = &HeirMatchRosters{
			A: HeirMatchRoster(t.Rosters.A),
			B: HeirMatchRoster(t.Rosters.B),
		}
	}
	return file
}
