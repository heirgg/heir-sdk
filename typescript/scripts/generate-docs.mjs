// Public declarations only. No source bodies or private members belong in SDK reference pages.
import {createHash} from "node:crypto";
import {mkdir, readFile, readdir, writeFile} from "node:fs/promises";
import {dirname, relative, resolve} from "node:path";
import {fileURLToPath} from "node:url";
import ts from "../tools/codegen/node_modules/typescript/lib/typescript.js";

const language = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repository = resolve(language, "..");
const target = resolve(repository, "docs/reference/typescript.mdx");
const check = process.argv.includes("--check");
if (process.argv.slice(2).some(argument => argument !== "--check")) throw new Error("Usage: node typescript/scripts/generate-docs.mjs [--check]");

async function sourceFiles(directory) {
  const entries = await readdir(directory, {withFileTypes: true});
  const nested = await Promise.all(entries.map(entry => entry.isDirectory()
    ? sourceFiles(resolve(directory, entry.name))
    : entry.name.endsWith(".ts") ? [resolve(directory, entry.name)] : []));
  return nested.flat().sort();
}

const specDirectory = resolve(repository, "spec");
const specs = (await readdir(specDirectory)).filter(name => name.endsWith(".json")).map(name => resolve(specDirectory, name));
const files = [...await sourceFiles(resolve(language, "src")), resolve(language, "package.json"), ...specs].sort();
const digest = createHash("sha256");
for (const file of files) digest.update(relative(repository, file).replaceAll("\\", "/")).update("\0").update(await readFile(file)).update("\0");
const hash = digest.digest("hex");
const manifest = JSON.parse(await readFile(resolve(language, "package.json"), "utf8"));
const config = ts.readConfigFile(resolve(language, "tsconfig.json"), ts.sys.readFile);
if (config.error) throw new Error(ts.flattenDiagnosticMessageText(config.error.messageText, "\n"));
const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, language);
const entry = resolve(language, "src/index.ts");
const program = ts.createProgram([entry], parsed.options);
const diagnostics = [...program.getSyntacticDiagnostics(), ...program.getSemanticDiagnostics()];
if (diagnostics.length) throw new Error(ts.formatDiagnosticsWithColorAndContext(diagnostics, {
  getCurrentDirectory: () => language, getCanonicalFileName: name => name, getNewLine: () => "\n"
}));
const checker = program.getTypeChecker();
const entryFile = program.getSourceFile(entry);
const moduleSymbol = checker.getSymbolAtLocation(entryFile);
const exported = checker.getExportsOfModule(moduleSymbol).map(symbol => {
  const resolved = symbol.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(symbol) : symbol;
  const declaration = resolved.valueDeclaration ?? resolved.declarations?.[0];
  if (!declaration) throw new Error(`No declaration for export ${symbol.name}`);
  return {name: symbol.name, symbol: resolved, declaration};
}).sort((a, b) => {
  const left = a.name.toLowerCase();
  const right = b.name.toLowerCase();
  return left < right ? -1 : left > right ? 1 : a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
});

const printer = ts.createPrinter({newLine: ts.NewLineKind.LineFeed, removeComments: true});
const format = ts.TypeFormatFlags.NoTruncation | ts.TypeFormatFlags.InTypeAlias;
const nodeFlags = ts.NodeBuilderFlags.NoTruncation | ts.NodeBuilderFlags.InTypeAlias;
const has = (node, kind) => node.modifiers?.some(modifier => modifier.kind === kind);
const visible = node => !has(node, ts.SyntaxKind.PrivateKeyword) && !has(node, ts.SyntaxKind.ProtectedKeyword) && !ts.isPrivateIdentifier(node.name ?? ts.factory.createIdentifier("unused"));
const print = (node, source) => printer.printNode(ts.EmitHint.Unspecified, node, source).trim();
const typeText = (node, source) => node ? print(node, source) : "unknown";
const inferred = (node, source) => checker.typeToString(checker.getTypeAtLocation(node), source, format);
const parameter = (node, source) => `${node.dotDotDotToken ? "..." : ""}${print(node.name, source)}${node.questionToken || node.initializer ? "?" : ""}: ${node.type ? typeText(node.type, source) : inferred(node, source)}`;
const generics = (node, source) => node.typeParameters?.length ? `<${node.typeParameters.map(value => print(value, source)).join(", ")}>` : "";

function classDeclaration({name, declaration}) {
  const source = declaration.getSourceFile();
  const heritage = declaration.heritageClauses?.map(value => print(value, source)).join(" ") ?? "";
  const lines = [`export class ${name}${generics(declaration, source)}${heritage ? ` ${heritage}` : ""} {`];
  for (const member of declaration.members) {
    if (!visible(member)) continue;
    if (ts.isConstructorDeclaration(member)) {
      for (const value of member.parameters) {
        if (!visible(value)) continue;
        if (has(value, ts.SyntaxKind.PublicKeyword) || has(value, ts.SyntaxKind.ReadonlyKeyword)) {
          lines.push(`  ${has(value, ts.SyntaxKind.ReadonlyKeyword) ? "readonly " : ""}${print(value.name, source)}: ${value.type ? typeText(value.type, source) : inferred(value, source)};`);
        }
      }
      lines.push(`  constructor(${member.parameters.map(value => parameter(value, source)).join(", ")});`);
    } else if (ts.isPropertyDeclaration(member)) {
      lines.push(`  ${has(member, ts.SyntaxKind.StaticKeyword) ? "static " : ""}${has(member, ts.SyntaxKind.ReadonlyKeyword) ? "readonly " : ""}${print(member.name, source)}${member.questionToken ? "?" : ""}: ${member.type ? typeText(member.type, source) : inferred(member, source)};`);
    } else if (ts.isMethodDeclaration(member) || ts.isGetAccessorDeclaration(member) || ts.isSetAccessorDeclaration(member)) {
      const signature = checker.getSignatureFromDeclaration(member);
      const returns = member.type ? typeText(member.type, source) : checker.typeToString(checker.getReturnTypeOfSignature(signature), member, format);
      const prefix = ts.isGetAccessorDeclaration(member) ? "get " : ts.isSetAccessorDeclaration(member) ? "set " : "";
      lines.push(`  ${has(member, ts.SyntaxKind.StaticKeyword) ? "static " : ""}${prefix}${print(member.name, source)}${member.questionToken ? "?" : ""}${generics(member, source)}(${member.parameters.map(value => parameter(value, source)).join(", ")}): ${returns};`);
    }
  }
  lines.push("}");
  return lines.join("\n");
}

function declarationText(value) {
  const {name, symbol, declaration} = value;
  const source = declaration.getSourceFile();
  if (ts.isClassDeclaration(declaration)) return classDeclaration(value);
  if (ts.isVariableDeclaration(declaration)) return `export const ${name}: ${inferred(declaration, declaration)};`;
  if (ts.isTypeAliasDeclaration(declaration)) {
    const type = checker.getDeclaredTypeOfSymbol(symbol);
    const node = checker.typeToTypeNode(type, declaration, nodeFlags);
    if (!node) throw new Error(`Cannot render type ${name}`);
    const multiline = current => {
      if (ts.isTypeLiteralNode(current)) ts.setEmitFlags(current, ts.EmitFlags.MultiLine);
      ts.forEachChild(current, multiline);
    };
    multiline(node);
    return `export type ${name}${generics(declaration, source)} = ${print(node, source)};`;
  }
  if (ts.isInterfaceDeclaration(declaration)) {
    const prefix = name.startsWith("Public") ? "Public" : name.startsWith("Stat") ? "Stat" : "";
    const aliases = prefix ? {components: `${prefix}Components`, operations: `${prefix}Operations`, paths: `${prefix}Paths`} : {};
    const renamed = ts.factory.updateInterfaceDeclaration(declaration, [ts.factory.createModifier(ts.SyntaxKind.ExportKeyword)], name, declaration.typeParameters, declaration.heritageClauses, declaration.members.filter(visible));
    const transform = ts.transform(renamed, [context => {
      const visit = node => ts.isIdentifier(node) && aliases[node.text] ? ts.factory.createIdentifier(aliases[node.text]) : ts.visitEachChild(node, visit, context);
      return node => ts.visitNode(node, visit);
    }]);
    try { return print(transform.transformed[0], source); }
    finally { transform.dispose(); }
  }
  throw new Error(`Unhandled public declaration ${name}: ${ts.SyntaxKind[declaration.kind]}`);
}

function prose(text) {
  // Keep source inline-code spans while escaping characters interpreted as MDX.
  return text.split(/(`[^`]*`)/g).map(part => part.startsWith("`") ? part : part.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll("{", "&#123;").replaceAll("}", "&#125;")).join("");
}

const raw = new Set(["PublicPaths", "PublicOperations", "PublicComponents", "StatPaths", "StatOperations", "StatComponents"]);
const groups = [
  ["Runtime exports", value => ts.isClassDeclaration(value.declaration) || ts.isVariableDeclaration(value.declaration)],
  ["Options and helper interfaces", value => ts.isInterfaceDeclaration(value.declaration) && !raw.has(value.name)],
  ["Models and query types", value => ts.isTypeAliasDeclaration(value.declaration)],
  ["Raw OpenAPI types", value => raw.has(value.name)]
];
const output = [
  "---", "title: TypeScript source reference", 'description: "Public exports, client methods, options, and model fields generated from the SDK source."', `sdkSourceHash: "${hash}"`, "---", "",
  `{/* Generated by typescript/scripts/generate-docs.mjs. Edit SDK source, then regenerate. */}`, "",
  `This reference covers all ${exported.length} public exports of \`${manifest.name}\` at source version \`${manifest.version}\`. It describes a source snapshot, not a claim that this version is published or deployed.`, "",
  "Declarations omit implementations and private/protected members. Default values and operational behavior are documented in the [client guide](/sdk/typescript/client), [League methods](/sdk/typescript/league), [stat submission guide](/sdk/typescript/stats), and [transport guide](/sdk/typescript/transport).", "",
  "Model aliases are expanded to show their fields. Nested references resolve through the raw OpenAPI interfaces at the end of this page. Standard-library types retain their normal TypeScript meaning. `League` and `Stats` constructor signatures mention an internal transport; obtain those objects from `Heir` instead of constructing that transport.", ""
];
for (const [title, matches] of groups) {
  output.push(`## ${title}`, "");
  for (const value of exported.filter(matches)) {
    const source = value.declaration.getSourceFile();
    const path = relative(repository, source.fileName).replaceAll("\\", "/");
    const line = source.getLineAndCharacterOfPosition(value.declaration.getStart()).line + 1;
    const documentation = ts.displayPartsToString(value.symbol.getDocumentationComment(checker)).split(/\n\s*\n/)[0];
    output.push(`### ${value.name}`, "");
    if (documentation && !documentation.includes("```")) output.push(prose(documentation.replaceAll("\n", " ")), "");
    output.push(`[Source declaration](https://github.com/heirgg/heir-sdk/blob/main/${path}#L${line})`, "", "```typescript", declarationText(value), "```", "");
  }
}
const text = output.join("\n");
if (text.includes(repository)) throw new Error("Generated reference contains an absolute workspace path.");
const existing = await readFile(target, "utf8").catch(() => "");
if (check) {
  if (existing !== text) { console.error("TypeScript reference is stale. Run node typescript/scripts/generate-docs.mjs from the SDK repository."); process.exitCode = 1; }
  else console.log("TypeScript reference is up to date.");
} else if (existing !== text) {
  await mkdir(dirname(target), {recursive: true});
  await writeFile(target, text);
  console.log(`Wrote ${relative(repository, target)} (${exported.length} exports).`);
} else console.log("TypeScript reference is unchanged.");
