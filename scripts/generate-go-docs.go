// Command generate-go-docs writes the complete public Go SDK reference from its source declarations.
// Run from go/: go run ../scripts/generate-go-docs.go [--check].
package main

import (
	"bytes"
	"crypto/sha256"
	"flag"
	"fmt"
	"go/ast"
	"go/doc"
	"go/doc/comment"
	"go/format"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
)

const importPath = "github.com/heirgg/heir-sdk/go"

type declaration struct {
	name, kind, source, text, code, receiver string
}

func main() {
	_, source, _, ok := runtime.Caller(0)
	if !ok {
		fail("cannot locate generator source")
	}
	root := flag.String("root", filepath.Dir(filepath.Dir(source)), "SDK repository root")
	output := flag.String("output", "", "output MDX path (default: docs/reference/go.mdx under the SDK root)")
	check := flag.Bool("check", false, "compare generated content without writing files")
	flag.Parse()
	if flag.NArg() != 0 {
		fail("unexpected positional arguments")
	}
	target := *output
	if target == "" {
		target = filepath.Join(*root, "docs", "reference", "go.mdx")
	}
	content, err := generate(*root)
	if err != nil {
		fail("%v", err)
	}
	if *check {
		saved, err := os.ReadFile(target)
		if err != nil || !bytes.Equal(saved, content) {
			fail("Go reference is missing or stale; run go run ../scripts/generate-go-docs.go from go/.")
		}
		fmt.Println("Go SDK reference is up to date.")
		return
	}
	if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
		fail("%v", err)
	}
	if err := os.WriteFile(target, content, 0o644); err != nil {
		fail("%v", err)
	}
	fmt.Println("Wrote Go SDK reference.")
}

func fail(format string, args ...any) { fmt.Fprintf(os.Stderr, format+"\n", args...); os.Exit(1) }

func generate(root string) ([]byte, error) {
	paths, err := filepath.Glob(filepath.Join(root, "go", "*.go"))
	if err != nil {
		return nil, err
	}
	sort.Strings(paths)
	fset := token.NewFileSet()
	var files []*ast.File
	var declarations []declaration
	var packageComment string
	digest := sha256.New()
	hashFile := func(name string, content []byte) {
		fmt.Fprintf(digest, "%s\x00%d\x00", name, len(content))
		digest.Write(content)
	}
	module, err := os.ReadFile(filepath.Join(root, "go", "go.mod"))
	if err != nil {
		return nil, err
	}
	hashFile("go/go.mod", module)
	specPaths, err := filepath.Glob(filepath.Join(root, "spec", "*.json"))
	if err != nil {
		return nil, err
	}
	sort.Strings(specPaths)
	for _, path := range specPaths {
		content, err := os.ReadFile(path)
		if err != nil {
			return nil, err
		}
		hashFile("spec/"+filepath.Base(path), content)
	}
	for _, path := range paths {
		if strings.HasSuffix(path, "_test.go") {
			continue
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			return nil, err
		}
		file, err := parser.ParseFile(fset, path, raw, parser.ParseComments)
		if err != nil {
			return nil, err
		}
		if file.Name.Name != "heir" {
			return nil, fmt.Errorf("unexpected package in %s", path)
		}
		name := "go/" + filepath.Base(path)
		if filepath.Base(path) == "doc.go" {
			packageComment = file.Doc.Text()
		}
		hashFile(name, raw)
		files = append(files, file)
		for _, node := range file.Decls {
			location := fmt.Sprintf("%s#L%d", name, fset.Position(node.Pos()).Line)
			switch node := node.(type) {
			case *ast.FuncDecl:
				receiver := ""
				if node.Recv != nil {
					receiver = typeName(node.Recv.List[0].Type)
				}
				if !ast.IsExported(node.Name.Name) || (receiver != "" && !ast.IsExported(receiver)) {
					continue
				}
				clone := *node
				clone.Body = nil
				clone.Doc = nil
				name := node.Name.Name
				if receiver != "" {
					name = receiver + "." + name
				}
				code, err := formatted(fset, &clone)
				if err != nil {
					return nil, err
				}
				declarations = append(declarations, declaration{name: name, kind: "function", source: location, text: node.Doc.Text(), code: code, receiver: receiver})
			case *ast.GenDecl:
				if node.Tok != token.TYPE && node.Tok != token.CONST && node.Tok != token.VAR {
					continue
				}
				for _, spec := range node.Specs {
					switch spec := spec.(type) {
					case *ast.TypeSpec:
						if !ast.IsExported(spec.Name.Name) {
							continue
						}
						clone := *spec
						clone.Doc = nil
						clone.Comment = nil
						clone.Type = publicType(spec.Type)
						code, err := formatted(fset, &ast.GenDecl{Tok: node.Tok, Specs: []ast.Spec{&clone}})
						if err != nil {
							return nil, err
						}
						text := spec.Doc.Text()
						if text == "" {
							text = node.Doc.Text()
						}
						declarations = append(declarations, declaration{name: spec.Name.Name, kind: "type", source: location, text: text, code: code})
					case *ast.ValueSpec:
						for index, name := range spec.Names {
							if !ast.IsExported(name.Name) {
								continue
							}
							clone := *spec
							clone.Names = []*ast.Ident{name}
							clone.Doc = nil
							clone.Comment = nil
							if len(spec.Values) == len(spec.Names) {
								clone.Values = []ast.Expr{spec.Values[index]}
							}
							code, err := formatted(fset, &ast.GenDecl{Tok: node.Tok, Specs: []ast.Spec{&clone}})
							if err != nil {
								return nil, err
							}
							text := spec.Doc.Text()
							if text == "" {
								text = node.Doc.Text()
							}
							declarations = append(declarations, declaration{name: name.Name, kind: node.Tok.String(), source: location, text: text, code: code})
						}
					}
				}
			}
		}
	}
	if len(files) == 0 {
		return nil, fmt.Errorf("no SDK Go source files found")
	}
	pkg, err := doc.NewFromFiles(fset, files, importPath, doc.PreserveAST)
	if err != nil {
		return nil, err
	}
	sort.Slice(declarations, func(i, j int) bool { return declarations[i].name < declarations[j].name })
	var out bytes.Buffer
	fmt.Fprintf(&out, "---\ntitle: \"Go source reference\"\ndescription: \"Every exported Go SDK declaration, model field, enum constant, and method, generated from the SDK source.\"\nsdkSourceHash: \"%x\"\n---\n\n", digest.Sum(nil))
	out.WriteString("This reference is generated from the SDK's root Go package and includes every exported declaration. It omits implementation bodies and private fields. For installation and complete workflows, start with [Go SDK](/sdk/go).\n\n")
	fmt.Fprintf(&out, "Package: `%s` · Import: `%s`\n\n", pkg.Name, importPath)
	if packageComment == "" {
		packageComment = pkg.Doc
	}
	out.WriteString(renderComment(packageComment))
	out.WriteString("\n## Contents\n\n")
	for _, kind := range []string{"type", "function", "const", "var"} {
		var names []string
		for _, d := range declarations {
			if d.kind == kind && d.receiver == "" {
				names = append(names, fmt.Sprintf("[%s](#%s)", d.name, anchor(d.name)))
			}
		}
		if len(names) > 0 {
			fmt.Fprintf(&out, "**%s:** %s.\n\n", category(kind), strings.Join(names, ", "))
		}
	}
	for _, kind := range []string{"function", "const", "var", "type"} {
		var entries []declaration
		for _, d := range declarations {
			if d.kind == kind && d.receiver == "" {
				entries = append(entries, d)
			}
		}
		if len(entries) == 0 {
			continue
		}
		fmt.Fprintf(&out, "## %s\n\n", category(kind))
		for _, d := range entries {
			writeDeclaration(&out, d, 3)
			if d.kind == "type" {
				for _, method := range declarations {
					if method.receiver == d.name {
						writeDeclaration(&out, method, 4)
					}
				}
			}
		}
	}
	return out.Bytes(), nil
}

func category(kind string) string {
	switch kind {
	case "type":
		return "Types and methods"
	case "function":
		return "Functions"
	case "const":
		return "Constants"
	default:
		return "Variables"
	}
}
func anchor(name string) string { return strings.ToLower(strings.ReplaceAll(name, ".", "")) }
func writeDeclaration(out *bytes.Buffer, d declaration, level int) {
	fmt.Fprintf(out, "%s %s\n\n", strings.Repeat("#", level), d.name)
	if d.text != "" {
		out.WriteString(renderComment(d.text))
		out.WriteString("\n")
	}
	fmt.Fprintf(out, "```go\n%s\n```\n\n[Source](https://github.com/heirgg/heir-sdk/blob/main/%s).\n\n", d.code, d.source)
}
func renderComment(text string) string {
	var parser comment.Parser
	printer := comment.Printer{HeadingLevel: 5, DocLinkURL: func(link *comment.DocLink) string {
		if link.ImportPath != "" {
			return link.DefaultURL("https://pkg.go.dev/")
		}
		name := link.Name
		if link.Recv != "" {
			name = link.Recv + "." + name
		}
		return "#" + anchor(name)
	}}
	lines := strings.Split(string(printer.Markdown(parser.Parse(text))), "\n")
	var out strings.Builder
	inCode := false
	escape := strings.NewReplacer("<", "&lt;", ">", "&gt;", "{", "&#123;", "}", "&#125;")
	for i, line := range lines {
		if strings.HasPrefix(line, "\t") {
			if !inCode {
				out.WriteString("```go\n")
				inCode = true
			}
			out.WriteString(strings.TrimPrefix(line, "\t") + "\n")
			continue
		}
		if inCode && line == "" && i+1 < len(lines) && strings.HasPrefix(lines[i+1], "\t") {
			out.WriteString("\n")
			continue
		}
		if inCode {
			out.WriteString("```\n")
			inCode = false
		}
		out.WriteString(escape.Replace(strings.ReplaceAll(line, "\\`", "`")) + "\n")
	}
	if inCode {
		out.WriteString("```\n")
	}
	return out.String()
}
func formatted(fset *token.FileSet, node any) (string, error) {
	var out bytes.Buffer
	if err := format.Node(&out, fset, node); err != nil {
		return "", err
	}
	return strings.TrimSpace(out.String()), nil
}
func typeName(expression ast.Expr) string {
	switch value := expression.(type) {
	case *ast.Ident:
		return value.Name
	case *ast.StarExpr:
		return typeName(value.X)
	case *ast.IndexExpr:
		return typeName(value.X)
	case *ast.IndexListExpr:
		return typeName(value.X)
	case *ast.SelectorExpr:
		return value.Sel.Name
	}
	return ""
}
func publicType(expression ast.Expr) ast.Expr {
	switch value := expression.(type) {
	case *ast.StructType:
		clone := *value
		fields := *value.Fields
		fields.List = nil
		for _, field := range value.Fields.List {
			f := *field
			f.Names = nil
			for _, name := range field.Names {
				if ast.IsExported(name.Name) {
					f.Names = append(f.Names, name)
				}
			}
			if len(field.Names) > 0 && len(f.Names) == 0 {
				continue
			}
			if len(field.Names) == 0 && !ast.IsExported(typeName(field.Type)) {
				continue
			}
			f.Type = publicType(f.Type)
			fields.List = append(fields.List, &f)
		}
		clone.Fields = &fields
		return &clone
	case *ast.InterfaceType:
		clone := *value
		fields := *value.Methods
		fields.List = nil
		for _, field := range value.Methods.List {
			if len(field.Names) > 0 && !ast.IsExported(field.Names[0].Name) {
				continue
			}
			fields.List = append(fields.List, field)
		}
		clone.Methods = &fields
		return &clone
	}
	return expression
}
