import path from 'node:path';

import type {AttachmentPayload} from './types.js';

export function formatAttachmentLabel(attachment: AttachmentPayload, index: number): string {
	const kind = attachment.kind.toLowerCase();
	const label = kind === 'image' ? `Image #${index}` : `${capitalize(kind)} #${index}`;
	const fileName = attachment.file_name?.trim() || path.basename(attachment.path?.trim() || '') || `${kind}-${index}`;
	const meta: string[] = [];
	if (attachment.width && attachment.height) {
		meta.push(`${attachment.width}x${attachment.height}`);
	}
	if (attachment.byte_count && attachment.byte_count > 0) {
		meta.push(formatBytes(attachment.byte_count));
	}
	if (attachment.source?.trim()) {
		meta.push(attachment.source.trim());
	}
	return `${label} ${fileName}${meta.length > 0 ? ` (${meta.join(', ')})` : ''}`;
}

function formatBytes(bytes: number): string {
	if (bytes < 1024) {
		return `${bytes} B`;
	}
	if (bytes < 1024 * 1024) {
		return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
	}
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function capitalize(value: string): string {
	return value ? value[0]!.toUpperCase() + value.slice(1) : value;
}
