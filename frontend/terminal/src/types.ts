export type FrontendConfig = {
	backend_command: string[];
	initial_prompt?: string | null;
};

export type AttachmentPayload = {
	id: string;
	kind: string;
	file_name?: string;
	mime_type?: string;
	path?: string;
	byte_count?: number;
	width?: number;
	height?: number;
	source?: string;
};

export type TranscriptItem = {
	id?: string;
	role: 'system' | 'user' | 'assistant' | 'tool' | 'tool_result' | 'log';
	text: string;
	tool_name?: string;
	tool_input?: Record<string, unknown>;
	is_error?: boolean;
	attachments?: AttachmentPayload[];
	metadata?: Record<string, unknown>;
};

export type TaskSnapshot = {
	id: string;
	type: string;
	status: string;
	description: string;
	metadata?: Record<string, string>;
};

export type SelectOptionPayload = {
	value: string;
	label: string;
	description?: string;
};

export type BackendEvent = {
	type: string;
	message?: string | null;
	item?: TranscriptItem | null;
	items?: TranscriptItem[] | null;
	attachment?: AttachmentPayload | null;
	state?: Record<string, unknown> | null;
	tasks?: TaskSnapshot[] | null;
	commands?: string[] | null;
	modal?: Record<string, unknown> | null;
	select_options?: SelectOptionPayload[] | null;
	tool_name?: string | null;
	output?: string | null;
	is_error?: boolean | null;
	metadata?: Record<string, unknown> | null;
};
