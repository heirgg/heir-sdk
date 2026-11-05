// Command gen writes the SDK's types from the OpenAPI documents in ../../../spec, using oapi-codegen for models only.
//
// Before generating, each document is reshaped so the Go types read well; nothing about the wire format changes, only
// its Go spelling:
//   - each request and response body named in `names` (`<operationId> request`, `<operationId> <status>`) becomes the
//     component of that name, whether the document writes it inline or under another component name;
//   - every inline object becomes a named component, so a caller can name the type (the names in `names`, otherwise
//     <Parent><Field>); a named type's own fields are listed under its name (`Player.mmr`), wherever the type appears;
//   - a string enum listed in `names` becomes a named type, shared by every field that carries the same values;
//   - a union of numeric literals (0 | 1) or of a string with a literal collapses to one primitive;
//   - a boolean literal becomes a plain boolean.
//
// `-check` fails instead of writing when the committed files are out of date.
package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"sort"
	"strings"

	"github.com/getkin/kin-openapi/openapi3"
	"github.com/oapi-codegen/oapi-codegen/v2/pkg/codegen"
)

type schema = map[string]any

// names gives type names to inline shapes and shared enums, by their place in the document: `Parent.field`,
// `Parent.field[]` for an array's items, `Parent.field{}` for a map's values, and `operationId request` or
// `operationId 200` for an operation's bodies. The same name on several places means one type, and the places must agree. The table is ../../../spec/type-names.json, shared with the other SDKs'
// generators so every language calls a shape the same thing.
var names map[string]string

var documents = []struct {
	file, out string
	exclude   []string
}{
	// The error envelopes are written by hand (APIError), so both documents' `Error` schemas are left out.
	{file: "public-openapi.json", out: "types_public.gen.go", exclude: []string{"Error", "LeagueError"}},
	{file: "stat-submission-openapi.json", out: "types_stats.gen.go", exclude: []string{"Error"}},
}

func main() {
	specDir := flag.String("spec", "../../../spec", "the directory holding the OpenAPI documents")
	outDir := flag.String("out", "../..", "the package directory to write into")
	check := flag.Bool("check", false, "fail instead of writing when the committed files are out of date")
	flag.Parse()
	table, err := os.ReadFile(filepath.Join(*specDir, "type-names.json"))
	if err != nil {
		fail("%v", err)
	}
	if err := json.Unmarshal(table, &names); err != nil {
		fail("type-names.json: %v", err)
	}

	var stale []string
	for _, document := range documents {
		code, err := generate(filepath.Join(*specDir, document.file), document.exclude)
		if err != nil {
			fail("%s: %v", document.file, err)
		}
		target := filepath.Join(*outDir, document.out)
		committed, _ := os.ReadFile(target)
		if *check {
			if !bytes.Equal(committed, code) {
				stale = append(stale, document.out)
			}
			continue
		}
		if err := os.WriteFile(target, code, 0o644); err != nil {
			fail("%v", err)
		}
		fmt.Printf("Wrote %s\n", target)
	}
	if len(stale) > 0 {
		fail("Out of date: %s. Run `go generate ./...` and commit the result.", strings.Join(stale, ", "))
	}
	if *check {
		fmt.Println("Generated types are up to date.")
	}
}

func fail(format string, args ...any) {
	fmt.Fprintf(os.Stderr, format+"\n", args...)
	os.Exit(1)
}

func generate(path string, exclude []string) ([]byte, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var doc schema
	if err := json.Unmarshal(raw, &doc); err != nil {
		return nil, err
	}
	if err := nameOperations(doc); err != nil {
		return nil, err
	}
	reshape(doc, exclude)
	// Models only: the client is written by hand, so the operations are not needed.
	delete(doc, "paths")
	data, err := json.Marshal(doc)
	if err != nil {
		return nil, err
	}
	loaded, err := openapi3.NewLoader().LoadFromData(data)
	if err != nil {
		return nil, fmt.Errorf("loading the reshaped document: %w", err)
	}
	version := "v2.8.1"
	code, err := codegen.Generate(loaded, codegen.Configuration{
		PackageName:          "heir",
		Generate:             codegen.GenerateOptions{Models: true},
		NoVCSVersionOverride: &version,
		// Enum constants carry their type's name (CategoryCompetitive, MatchTypeCompetitive), so two enums may share a value.
		Compatibility: codegen.CompatibilityOptions{AlwaysPrefixEnumValues: true},
		OutputOptions: codegen.OutputOptions{
			SkipPrune:      true,
			ExcludeSchemas: exclude,
			// Go spelling for identifiers: ProfileURL, MatchID, TeamMMR.
			NameNormalizer:        "ToCamelCaseWithInitialisms",
			AdditionalInitialisms: []string{"MMR"},
			// A missing slice or map is nil; a pointer to one helps nobody.
			PreferSkipOptionalPointerOnContainerTypes: true,
			TypeMapping: &codegen.TypeMapping{
				// Whole numbers include millisecond timestamps, so 64 bits everywhere; a UUID is a string. A number, which may be a
				// fraction, is a float64 rather than a json.Number: encoding/json writes a whole float64 as 10, not 10.0, so a stat
				// read and sent again keeps its JSON form, and a caller does arithmetic without parsing.
				Integer: codegen.FormatMapping{Default: codegen.SimpleTypeSpec{Type: "int64"}},
				Number:  codegen.FormatMapping{Default: codegen.SimpleTypeSpec{Type: "float64"}},
				String:  codegen.FormatMapping{Formats: map[string]codegen.SimpleTypeSpec{"uuid": {Type: "string"}}},
			},
		},
	})
	if err != nil {
		return nil, err
	}
	header := "// Code generated by internal/gen from ../spec/" + filepath.Base(path) + "; DO NOT EDIT. Run `go generate ./...` after a spec change.\n\n"
	return []byte(header + code), nil
}

// nameOperations makes each request and response body named in `names` the component of that name. The backend
// writes most bodies inline, and some under names of its own; the SDKs name them the same way in every language. A body
// with no documented fields cannot become a type and is refused, so the gap is fixed in the backend document rather than
// shipped as an empty type.
func nameOperations(doc schema) error {
	schemas := doc["components"].(schema)["schemas"].(schema)
	paths, _ := doc["paths"].(schema)
	for _, path := range sortedKeys(paths) {
		methods := paths[path].(schema)
		for _, method := range sortedKeys(methods) {
			operation, ok := methods[method].(schema)
			if !ok || operation["operationId"] == nil {
				continue
			}
			bodies := map[string]any{"request": operation["requestBody"]}
			responses, _ := operation["responses"].(schema)
			for status, response := range responses {
				bodies[status] = response
			}
			for _, slot := range sortedKeys(bodies) {
				key := fmt.Sprintf("%v %s", operation["operationId"], slot)
				name, named := names[key]
				body, _ := bodies[slot].(schema)
				content, _ := body["content"].(schema)
				media, _ := content["application/json"].(schema)
				if !named || media == nil {
					continue
				}
				found := media["schema"].(schema)
				if ref, isRef := found["$ref"].(string); isRef {
					if err := rename(doc, ref[strings.LastIndex(ref, "/")+1:], name); err != nil {
						return err
					}
					continue
				}
				if found["properties"] == nil {
					return fmt.Errorf("%s (%s %s) documents no fields, so %s would be empty", key, strings.ToUpper(method), path, name)
				}
				copied := deepCopy(found)
				for _, key := range []string{"description", "example", "examples"} {
					delete(copied, key)
				}
				if existing, ok := schemas[name]; ok && !reflect.DeepEqual(existing, copied) {
					return fmt.Errorf("two different shapes are both named %s: reshaping needs a second name", name)
				}
				schemas[name] = copied
				media["schema"] = schema{"$ref": "#/components/schemas/" + name}
			}
		}
	}
	return nil
}

// rename renames the component `old` to `name`, and every reference to it.
func rename(doc schema, old, name string) error {
	if old == name {
		return nil
	}
	schemas := doc["components"].(schema)["schemas"].(schema)
	if _, taken := schemas[name]; taken {
		return fmt.Errorf("cannot rename %s: a component is already named %s", old, name)
	}
	schemas[name] = schemas[old]
	delete(schemas, old)
	target, replacement := "#/components/schemas/"+old, "#/components/schemas/"+name
	var visit func(node any)
	visit = func(node any) {
		switch node := node.(type) {
		case schema:
			if node["$ref"] == target {
				node["$ref"] = replacement
			}
			for _, value := range node {
				visit(value)
			}
		case []any:
			for _, value := range node {
				visit(value)
			}
		}
	}
	visit(doc)
	return nil
}

func sortedKeys(node schema) []string {
	keys := make([]string, 0, len(node))
	for key := range node {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

// reshaped holds the components reshaped so far. A document's own component can be reached as a field's type before
// its turn comes as a root; it is reshaped then, so it is compared with a newcomer in the same form.
var reshaped = map[string]bool{}

// reshape names every inline shape and shared enum in the document's components, in place. Excluded components
// are left alone: nothing of theirs is generated.
func reshape(doc schema, exclude []string) {
	schemas := doc["components"].(schema)["schemas"].(schema)
	reshaped = map[string]bool{}
	roots := make([]string, 0, len(schemas))
	for name := range schemas {
		if !slices.Contains(exclude, name) {
			roots = append(roots, name)
		}
	}
	sort.Strings(roots)
	for _, name := range roots {
		if !reshaped[name] {
			reshaped[name] = true
			walk(schemas, name, name, schemas[name].(schema))
		}
	}
}

// walk reshapes one object schema's properties. `path` is its place in the document and `goName` its Go type.
func walk(schemas schema, path, goName string, node schema) {
	collapse(node)
	properties, _ := node["properties"].(schema)
	fields := make([]string, 0, len(properties))
	for field := range properties {
		fields = append(fields, field)
	}
	sort.Strings(fields)
	for _, field := range fields {
		place(schemas, path+"."+field, goName+pascal(field), properties[field].(schema))
	}
}

// place reshapes the schema found at `path` (a field, an array's items or a map's values), hoisting it when it is an
// inline object or a named enum.
func place(schemas schema, path, autoName string, slot schema) {
	inner, set := unwrapNullable(slot)
	collapse(inner)
	if _, isRef := inner["$ref"]; isRef {
		return
	}
	switch {
	case inner["properties"] != nil:
		name := nameFor(path, autoName)
		// A named type's fields are listed under its name, so it is spelled the same wherever it appears.
		within := path
		if _, named := names[path]; named {
			within = name
		}
		_, known := schemas[name]
		hoisted := hoist(schemas, within, name, inner)
		set(name)
		if !known {
			walk(schemas, within, name, hoisted)
		}
	case inner["type"] == "array":
		if items, ok := inner["items"].(schema); ok {
			place(schemas, path+"[]", autoName+"Item", items)
		}
	case inner["type"] == "string" && inner["enum"] != nil:
		if name, named := names[path]; named {
			hoist(schemas, name, name, inner)
			set(name)
		}
	}
	if values, ok := inner["additionalProperties"].(schema); ok && values["properties"] != nil {
		place(schemas, path+"{}", autoName+"Value", values)
	}
}

func nameFor(path, autoName string) string {
	if name, ok := names[path]; ok {
		return name
	}
	return autoName
}

// hoist stores `node` as the component `name`, or checks that it agrees with the one already there, and returns the
// stored copy. `path` is the place the type's own fields are listed under.
func hoist(schemas schema, path, name string, node schema) schema {
	copied := deepCopy(node)
	delete(copied, "description") // the field's description stays on the field; the type gets none
	if existing, ok := schemas[name]; ok {
		stored := existing.(schema)
		if !reshaped[name] {
			reshaped[name] = true
			walk(schemas, name, name, stored)
		}
		// The stored one has been reshaped all the way down; reshape the newcomer the same way before comparing.
		walk(schemas, path, name, copied)
		comparable := deepCopy(stored)
		delete(comparable, "description")
		if !reflect.DeepEqual(comparable, copied) {
			fail("two different shapes are both named %s: reshaping needs a second name", name)
		}
		return stored
	}
	reshaped[name] = true
	schemas[name] = copied
	return copied
}

// unwrapNullable finds the schema inside a nullable wrapper (`anyOf: [X, null]`), and how to replace it with a reference.
func unwrapNullable(slot schema) (inner schema, set func(name string)) {
	if members, ok := slot["anyOf"].([]any); ok && len(members) == 2 {
		for index, member := range members {
			other := members[1-index].(schema)
			if m, ok := member.(schema); ok && m["type"] == "null" {
				return other, func(name string) { members[1-index] = schema{"$ref": "#/components/schemas/" + name} }
			}
		}
	}
	return slot, func(name string) {
		description, _ := slot["description"]
		for key := range slot {
			delete(slot, key)
		}
		slot["$ref"] = "#/components/schemas/" + name
		if description != nil {
			slot["description"] = description
		}
	}
}

// collapse rewrites unions a Go type cannot express well into one primitive, and a boolean literal into a boolean.
func collapse(node schema) {
	if members, ok := node["anyOf"].([]any); ok && len(members) > 0 {
		kind, allLiteral, integral := "", true, true
		var values []any
		for _, raw := range members {
			member, _ := raw.(schema)
			memberKind, _ := member["type"].(string)
			if memberKind == "integer" {
				memberKind = "number"
			}
			if memberKind == "" || (kind != "" && memberKind != kind) {
				return
			}
			kind = memberKind
			literal, isLiteral := member["const"]
			if !isLiteral {
				allLiteral = false
			} else {
				values = append(values, literal)
				if number, ok := literal.(float64); !ok || number != float64(int64(number)) {
					integral = false
				}
			}
		}
		delete(node, "anyOf")
		switch {
		case kind == "number" && allLiteral && integral:
			node["type"] = "integer"
		case kind == "string" && allLiteral:
			node["type"], node["enum"] = "string", values
		default:
			node["type"] = kind
		}
	}
	if node["type"] == "boolean" {
		delete(node, "const")
	}
	// A string literal is a one-value enum, so it can be named and shared like any other.
	if literal, ok := node["const"]; ok && node["type"] == "string" {
		delete(node, "const")
		node["enum"] = []any{literal}
	}
}

func deepCopy(node schema) schema {
	data, _ := json.Marshal(node)
	var copied schema
	_ = json.Unmarshal(data, &copied)
	return copied
}

func pascal(field string) string {
	if field == "" {
		return ""
	}
	return strings.ToUpper(field[:1]) + field[1:]
}
