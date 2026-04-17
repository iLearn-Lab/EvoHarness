import {createWriteStream} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';

export type ClipboardImageCapture = {
	path: string;
	fileName: string;
	mimeType: string;
	source: 'clipboard';
};

export async function captureClipboardImage(): Promise<ClipboardImageCapture> {
	const tempDir = await mkdtemp(path.join(os.tmpdir(), 'evo-harness-clipboard-'));
	const fileName = `clipboard-${Date.now()}.png`;
	const outputPath = path.join(tempDir, fileName);

	if (process.platform === 'win32') {
		await captureWindowsClipboardImage(outputPath);
		return {path: outputPath, fileName, mimeType: 'image/png', source: 'clipboard'};
	}

	if (process.platform === 'darwin') {
		await captureMacClipboardImage(outputPath);
		return {path: outputPath, fileName, mimeType: 'image/png', source: 'clipboard'};
	}

	if (process.platform === 'linux') {
		await captureLinuxClipboardImage(outputPath);
		return {path: outputPath, fileName, mimeType: 'image/png', source: 'clipboard'};
	}

	throw new Error(`Clipboard image paste is not supported on ${process.platform}.`);
}

async function captureWindowsClipboardImage(outputPath: string): Promise<void> {
	const script = [
		"$ErrorActionPreference = 'Stop'",
		'Add-Type -AssemblyName System.Windows.Forms',
		'Add-Type -AssemblyName System.Drawing',
		"$image = $null",
		'try {',
		"  if (-not [System.Windows.Forms.Clipboard]::ContainsImage()) {",
		"    [Console]::Error.WriteLine('No image data found in the clipboard. Copy an image first, then try again.')",
		'    exit 1',
		'  }',
		'  $image = [System.Windows.Forms.Clipboard]::GetImage()',
		"  if ($null -eq $image) { throw 'No image data found in the clipboard. Copy an image first, then try again.' }",
		`$target = '${escapePowerShell(outputPath)}'`,
		'  $image.Save($target, [System.Drawing.Imaging.ImageFormat]::Png)',
		'} catch {',
		'  [Console]::Error.WriteLine($_.Exception.Message)',
		'  exit 1',
		'} finally {',
		'  if ($null -ne $image) { $image.Dispose() }',
		'}',
	].join('; ');

	await runCommand('powershell', ['-NoProfile', '-STA', '-Command', script]);
}

async function captureMacClipboardImage(outputPath: string): Promise<void> {
	await runCommand('pngpaste', [outputPath], 'No image data found in the clipboard. Install pngpaste if this terminal cannot access images directly.');
}

async function captureLinuxClipboardImage(outputPath: string): Promise<void> {
	try {
		await pipeCommandToFile('wl-paste', ['--no-newline', '--type', 'image/png'], outputPath);
		return;
	} catch (_error) {
		// Fall through to X11 clipboard tools.
	}

	try {
		await pipeCommandToFile('xclip', ['-selection', 'clipboard', '-t', 'image/png', '-o'], outputPath);
		return;
	} catch (_error) {
		// Fall through.
	}

	await pipeCommandToFile('xsel', ['--clipboard', '--output'], outputPath, 'No clipboard image tool was available. Try installing wl-clipboard, xclip, or xsel.');
}

function runCommand(command: string, args: string[], fallbackMessage?: string): Promise<void> {
	return new Promise((resolve, reject) => {
		const child = spawn(command, args, {
			stdio: ['ignore', 'pipe', 'pipe'],
		});
		let stderr = '';
		child.stderr.on('data', (chunk) => {
			stderr += chunk.toString();
		});
		child.on('error', (error) => {
			reject(new Error(fallbackMessage ?? error.message));
		});
		child.on('close', (code) => {
			if (code === 0) {
				resolve();
				return;
			}
			reject(new Error(stderr.trim() || fallbackMessage || `Command failed: ${command}`));
		});
	});
}

function pipeCommandToFile(command: string, args: string[], outputPath: string, fallbackMessage?: string): Promise<void> {
	return new Promise((resolve, reject) => {
		const child = spawn(command, args, {
			stdio: ['ignore', 'pipe', 'pipe'],
		});
		const output = createWriteStream(outputPath);
		let stderr = '';

		child.stdout.pipe(output);
		child.stderr.on('data', (chunk) => {
			stderr += chunk.toString();
		});
		child.on('error', (error) => {
			output.destroy();
			reject(new Error(fallbackMessage ?? error.message));
		});
		child.on('close', (code) => {
			output.end(() => {
				if (code === 0) {
					resolve();
					return;
				}
				reject(new Error(stderr.trim() || fallbackMessage || `Command failed: ${command}`));
			});
		});
	});
}

function escapePowerShell(value: string): string {
	return value.replace(/'/g, "''");
}
