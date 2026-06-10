/**
 * Generates Zap. app icon as 512x512 PNG
 * Run: node generate-icon.js
 * Requires: npm install canvas
 */
const { createCanvas } = require("canvas");
const fs = require("fs");
const path = require("path");

const SIZE = 512;
const canvas = createCanvas(SIZE, SIZE);
const ctx = canvas.getContext("2d");

// Background — dark warm
ctx.fillStyle = "#1C1917";
ctx.beginPath();
// Rounded rect (radius 100)
const r = 100;
ctx.moveTo(r, 0);
ctx.lineTo(SIZE - r, 0);
ctx.quadraticCurveTo(SIZE, 0, SIZE, r);
ctx.lineTo(SIZE, SIZE - r);
ctx.quadraticCurveTo(SIZE, SIZE, SIZE - r, SIZE);
ctx.lineTo(r, SIZE);
ctx.quadraticCurveTo(0, SIZE, 0, SIZE - r);
ctx.lineTo(0, r);
ctx.quadraticCurveTo(0, 0, r, 0);
ctx.closePath();
ctx.fill();

// Orange circle behind bolt
ctx.fillStyle = "#E8571A";
ctx.beginPath();
ctx.arc(SIZE / 2, SIZE / 2 - 20, 155, 0, Math.PI * 2);
ctx.fill();

// Lightning bolt — drawn as polygon
ctx.fillStyle = "#ffffff";
ctx.beginPath();
// Bold lightning bolt centred at 256,236
// Top right → down-left → middle right overhang → down-left → bottom
ctx.moveTo(285, 130);   // top right
ctx.lineTo(210, 270);   // middle left
ctx.lineTo(255, 270);   // middle right
ctx.lineTo(220, 390);   // bottom left tip (extended)
ctx.lineTo(305, 240);   // middle right upper
ctx.lineTo(258, 240);   // middle left upper
ctx.lineTo(315, 130);   // top left
ctx.closePath();
ctx.fill();

// Wordmark — "Zap." below
ctx.fillStyle = "#ffffff";
ctx.font = "bold 80px -apple-system, sans-serif";
ctx.textAlign = "center";
ctx.textBaseline = "middle";
ctx.fillText("Zap", 230, 445);

// Orange dot
ctx.fillStyle = "#E8571A";
ctx.font = "bold 80px -apple-system, sans-serif";
ctx.fillText(".", 295, 445);

// Save
const outputPath = path.join(__dirname, "icon-512.png");
const buffer = canvas.toBuffer("image/png");
fs.writeFileSync(outputPath, buffer);
console.log("✅ Icon saved to", outputPath);
console.log("Copy to loot-app-v2/assets/icon.png and adaptive-icon.png");
