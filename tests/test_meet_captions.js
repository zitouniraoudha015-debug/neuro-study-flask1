const M = require("../extension/meet_captions.js");
const assert = require("assert");

// Reproduit l'écran de la capture : 3 intervenants + bouton « Aller en bas » + avatar « B »
const runs = [
  { text: "Vous", size: 18 }, { text: "Everyone.", size: 30 },
  { text: "B", size: 20 }, { text: "Bouazizi May", size: 18 }, { text: "Fish.", size: 30 },
  { text: "Vous", size: 18 },
  { text: "Hello, everyone. Hey, hello, everyone! We are gonna talk about the", size: 30 },
  { text: "conditioner. Between two members. We need her value. It's actually. He's.", size: 30 },
  { text: "arrow_downward", size: 24, junk: true }, { text: "Aller en bas", size: 16, junk: true },
  { text: "Désactiver le micro (Ctrl+d)", size: 14 },          // infobulle hors bouton : filtrée par le texte
  { text: "settings arrow_downward Aller en bas", size: 14 },  // doit disparaître
];
const blocks = M.groupRuns(runs);
console.log(JSON.stringify(blocks, null, 1));
assert.strictEqual(blocks.length, 3);
assert.deepStrictEqual(blocks.map(b => b.speaker), ["Vous", "Bouazizi May", "Vous"]);
assert.strictEqual(blocks[1].text, "Fish.");
assert.ok(blocks[2].text.startsWith("Hello, everyone.") && blocks[2].text.endsWith("He's."));
assert.ok(!blocks.some(b => /arrow_downward|Aller en bas|micro/i.test(b.text)));

// Fusion : la phrase s'allonge → une seule entrée ; nouvelle phrase → nouvelle entrée
const tr = [];
M.mergeBlocks(tr, [{ speaker: "Vous", text: "Hello everyone" }], 1000, null);
M.mergeBlocks(tr, [{ speaker: "Vous", text: "Hello, everyone. We are gonna talk" }], 2000, null);
assert.strictEqual(tr.length, 1);
assert.strictEqual(tr[0].text, "Hello, everyone. We are gonna talk");
M.mergeBlocks(tr, [{ speaker: "Vous", text: "Hello, everyone. We are gonna talk" }], 3000, null);   // rien de neuf
assert.strictEqual(tr.length, 1);
M.mergeBlocks(tr, [{ speaker: "Bouazizi May", text: "Fish." }, { speaker: "Vous", text: "The conditioner is a statement." }], 4000, null);
assert.strictEqual(tr.length, 3);
// même intervenant, phrase différente → nouvelle ligne
M.mergeBlocks(tr, [{ speaker: "Vous", text: "Now the second point is the mean." }], 5000, null);
assert.strictEqual(tr.length, 4);

// Pas de tailles distinctes → un seul bloc sans intervenant
const flat = M.groupRuns([{ text: "salam", size: 20 }, { text: "chnowa el moyenne", size: 20 }]);
assert.strictEqual(flat.length, 1); assert.strictEqual(flat[0].speaker, "");
// Mot parlé « settings » dans une vraie phrase : conservé
const spoken = M.groupRuns([{ text: "Open the settings page", size: 30 }]);
assert.strictEqual(spoken[0].text, "Open the settings page");
// Vide
assert.deepStrictEqual(M.groupRuns([]), []);
console.log("TOUS LES TESTS JS OK");
