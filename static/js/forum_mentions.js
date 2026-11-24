document.querySelectorAll('.forum-mention-picker').forEach((picker) => {
    const input = document.getElementById(picker.dataset.input);
    const suggestions = picker.querySelector('.list-group');
    const members = JSON.parse(picker.dataset.members);
    let selection = null;

    function updateSuggestions() {
        const cursor = input.selectionStart;
        const before = input.value.slice(0, cursor);
        const match = /(?:^|\s)@([^@\n]{0,80})$/.exec(before);
        suggestions.replaceChildren();
        selection = null;
        if (!match) {
            suggestions.hidden = true;
            return;
        }
        const query = match[1].toLocaleLowerCase();
        const matches = members.filter((member) => member.name.toLocaleLowerCase().includes(query));
        selection = { start: cursor - match[1].length - 1, end: cursor };
        matches.forEach((member) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'list-group-item list-group-item-action';
            const duplicate = members.filter((item) => item.name.toLocaleLowerCase() === member.name.toLocaleLowerCase()).length > 1;
            button.textContent = '@' + member.name + (duplicate ? ' (member ' + member.id + ')' : '');
            button.addEventListener('click', () => {
                if (!selection) return;
                const name = member.name.replace(/[\]\r\n]/g, ' ').trim() || 'Member';
                input.setRangeText('@[' + name + '](' + member.id + ') ', selection.start, selection.end, 'end');
                input.focus();
                suggestions.replaceChildren();
                suggestions.hidden = true;
                selection = null;
            });
            suggestions.appendChild(button);
        });
        if (!matches.length) {
            const message = document.createElement('div');
            message.className = 'list-group-item text-muted';
            message.textContent = 'No household members found.';
            suggestions.appendChild(message);
        }
        suggestions.hidden = false;
    }

    input.addEventListener('input', updateSuggestions);
    input.addEventListener('click', updateSuggestions);
    input.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            suggestions.hidden = true;
            selection = null;
        }
    });
});
