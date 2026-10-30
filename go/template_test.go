package heir

import (
	"encoding/json"
	"testing"
	"time"
)

func TestTemplateConvertsToSubmittableMatch(t *testing.T) {
	name, reference, gamemode, side := "Team", "my-match", "SKM", "a"
	template := MatchTemplate{
		Format: HeirMatchFormatHeirMatchV1, Reference: &reference, StartedAt: time.Date(2026, 10, 30, 12, 0, 0, 0, time.UTC),
		Gamemode: &HeirMatchGamemode{Key: &gamemode}, Rosters: &MatchTemplateRosters{A: MatchTemplateRoster{Name: &name}, B: MatchTemplateRoster{Name: &name}},
		Maps: []HeirMatchMap{{Winner: &side, Players: []HeirMatchPlayer{{Name: &name}}}},
	}
	expected, err := json.Marshal(template)
	if err != nil {
		t.Fatal(err)
	}
	file := template.ToMatchFile()
	actual, err := json.Marshal(file)
	if err != nil {
		t.Fatal(err)
	}
	assertContractJSON(t, actual, expected)
	if file.Rosters == nil || file.Rosters.A.Name == nil || *file.Rosters.A.Name != name {
		t.Fatal("rosters not converted")
	}
	template.Rosters = nil
	if template.ToMatchFile().Rosters != nil {
		t.Fatal("absent rosters should stay absent")
	}
}
