import React, {memo} from 'react';
import {Box, Text} from 'ink';

function CommandPickerInner({
	hints,
	selectedIndex,
}: {
	hints: string[];
	selectedIndex: number;
}): React.JSX.Element | null {
	if (hints.length === 0) {
		return null;
	}

	return (
		<Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={1} marginTop={1}>
			<Text color="cyan" bold>command palette  ::  quick jump (^_^)/</Text>
			{hints.map((hint, index) => {
				const isSelected = index === selectedIndex;
				return (
					<Text key={hint} color={isSelected ? 'cyan' : undefined} bold={isSelected}>
						{isSelected ? '>> ' : '   '}
						{hint}
					</Text>
				);
			})}
			<Text dimColor>up/down navigate  -  enter select  -  esc dismiss</Text>
		</Box>
	);
}

export const CommandPicker = memo(CommandPickerInner);
