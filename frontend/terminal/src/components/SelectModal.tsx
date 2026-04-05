import React from 'react';
import {Box, Text} from 'ink';

export type SelectOption = {
	value: string;
	label: string;
	description?: string;
	active?: boolean;
};

export function SelectModal({
	title,
	options,
	selectedIndex,
}: {
	title: string;
	options: SelectOption[];
	selectedIndex: number;
}): React.JSX.Element {
	return (
		<Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={1} marginTop={1}>
			<Text bold color="cyan">{title}  ::  choose your lane {'(^_^)/'}</Text>
			<Text> </Text>
			{options.map((option, index) => {
				const isSelected = index === selectedIndex;
				return (
					<Box key={option.value} flexDirection="column" marginBottom={index === options.length - 1 ? 0 : 1}>
						<Text color={isSelected ? 'cyan' : undefined} bold={isSelected}>
							{isSelected ? '» ' : '  '}
							{option.label}
							{option.active ? '  (current)' : ''}
						</Text>
						{option.description ? <Text dimColor>{option.description}</Text> : null}
					</Box>
				);
			})}
			<Text dimColor>↑↓ navigate  •  enter select  •  esc cancel</Text>
		</Box>
	);
}
