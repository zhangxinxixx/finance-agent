import { parseInlineMarkdown, parseMarkdown } from "./markdownViewerModel.js";

function expect(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

function expectArray(actual: unknown[], expected: unknown[], message: string): void {
  const actualJson = JSON.stringify(actual);
  const expectedJson = JSON.stringify(expected);
  expect(actualJson === expectedJson, `${message}: expected ${expectedJson}, got ${actualJson}`);
}

function testParsesMarkdownTableAsStructuredRows(): void {
  const blocks = parseMarkdown(`
| 因子 | 状态 | 判断 |
|---|---:|:---:|
| 实际利率 | 偏高 | 压制黄金 |
| DXY | 横盘 | A \\| B |
`);
  const table = blocks[0];

  expect(table?.type === "table", "first block should be a table");
  if (table?.type !== "table") return;

  expectArray(table.headers, ["因子", "状态", "判断"], "table headers");
  expectArray(table.aligns, ["left", "right", "center"], "table aligns");
  expectArray(table.rows, [["实际利率", "偏高", "压制黄金"], ["DXY", "横盘", "A | B"]], "table rows");
}

function testParsesInlineMarkdownTokens(): void {
  const tokens = parseInlineMarkdown("**重点变量** 是 `US10Y`，参考 [source](https://example.com)");

  expectArray(
    tokens.map((token) => token.type),
    ["bold", "text", "code", "text", "link"],
    "inline token types",
  );
  expect(tokens[0]?.text === "重点变量", "bold token text");
  expect(tokens[2]?.text === "US10Y", "code token text");
  expect(tokens[4]?.type === "link" && tokens[4].href === "https://example.com", "link token href");
}

testParsesMarkdownTableAsStructuredRows();
testParsesInlineMarkdownTokens();
