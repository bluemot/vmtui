import React, { useState, useEffect } from 'react';
import { Box, Text } from 'ink';
import SelectInput from 'ink-select-input';
import * as fs from 'fs/promises';
import * as path from 'path';

interface FileBrowserProps {
    onSelect: (path: string | null) => void;
    startPath: string;
    title: string;
    mode: 'file' | 'directory';
}

export const FileBrowser = ({ onSelect, startPath, title, mode }: FileBrowserProps) => {
    const [currentPath, setCurrentPath] = useState(path.resolve(startPath));
    const [items, setItems] = useState<{ label: string; value: string }[]>([]);

    useEffect(() => {
        const loadDir = async () => {
            try {
                const entries = await fs.readdir(currentPath, { withFileTypes: true });
                const dirs = entries
                    .filter(e => e.isDirectory())
                    .sort((a, b) => a.name.localeCompare(b.name))
                    .map(e => ({ label: `/${e.name}`, value: `dir:${e.name}` }));
                
                const files = entries
                    .filter(e => e.isFile() && (mode === 'file' ? (e.name.endsWith('.iso') || e.name.endsWith('.img') || e.name.endsWith('.qcow2')) : true))
                    .sort((a, b) => a.name.localeCompare(b.name))
                    .map(e => ({ label: e.name, value: `file:${e.name}` }));

                const menuItems = [
                    { label: '.. (Go Up)', value: 'up' },
                    ...(mode === 'directory' ? [{ label: ' [ SELECT CURRENT DIRECTORY ] ', value: 'select' }] : []),
                    ...dirs,
                    ...(mode === 'file' ? files : [])
                ];
                setItems(menuItems);
            } catch (e) {
                setItems([{ label: 'Error loading directory. Back.', value: 'up' }]);
            }
        };
        loadDir();
    }, [currentPath, mode]);

    const handleSelect = (item: any) => {
        if (item.value === 'up') {
            const parent = path.dirname(currentPath);
            if (parent === currentPath) {
                onSelect(null);
            } else {
                setCurrentPath(parent);
            }
        } else if (item.value === 'select') {
            onSelect(currentPath);
        } else if (item.value.startsWith('dir:')) {
            setCurrentPath(path.join(currentPath, item.value.substring(4)));
        } else if (item.value.startsWith('file:')) {
            onSelect(path.join(currentPath, item.value.substring(5)));
        }
    };

    return (
        <Box flexDirection="column">
            <Text bold color="blue">{title}: {currentPath}</Text>
            <SelectInput items={items} onSelect={handleSelect} />
            <Text dimColor>Press Esc/Q to cancel (handled by parent)</Text>
        </Box>
    );
};
