// Location suggestions for a comma-separated list: type to filter, click or Enter to add, x to clear.
const PLACES = [
    'Remote', 'Bengaluru', 'Mumbai', 'Pune', 'Hyderabad', 'Chennai', 'Delhi', 'Gurugram', 'Noida',
    'Kolkata', 'Ahmedabad', 'Jaipur', 'Chandigarh', 'Kochi', 'Indore', 'Coimbatore', 'Thiruvananthapuram',
    'Nagpur', 'Bhubaneswar', 'Lucknow', 'India', 'Dubai', 'Abu Dhabi', 'Riyadh', 'Doha', 'Singapore',
    'Kuala Lumpur', 'Bangkok', 'Jakarta', 'Manila', 'Hong Kong', 'Tokyo', 'Seoul', 'Sydney', 'Melbourne',
    'Auckland', 'London', 'Manchester', 'Edinburgh', 'Dublin', 'Berlin', 'Munich', 'Amsterdam', 'Paris',
    'Madrid', 'Barcelona', 'Lisbon', 'Zurich', 'Stockholm', 'Copenhagen', 'Warsaw', 'Prague', 'Tallinn',
    'New York', 'San Francisco', 'Seattle', 'Austin', 'Boston', 'Chicago', 'Los Angeles', 'Denver',
    'Atlanta', 'Dallas', 'Washington DC', 'Toronto', 'Vancouver', 'Montreal', 'Mexico City', 'Sao Paulo',
    'Buenos Aires', 'Tel Aviv', 'Cairo', 'Lagos', 'Nairobi', 'Cape Town', 'United States', 'United Kingdom',
    'Canada', 'Germany', 'Australia', 'UAE', 'Europe',
];

export function setupLocationSuggest(input, list, clearBtn) {
    let active = -1;
    let items = [];

    const parts = () => input.value.split(',');
    const chosen = () => parts().slice(0, -1).map((s) => s.trim().toLowerCase());
    const syncClear = () => { clearBtn.hidden = !input.value; };

    function close() { list.hidden = true; active = -1; }

    function render() {
        const query = parts().at(-1).trim().toLowerCase();
        const taken = new Set(chosen());
        items = PLACES.filter((p) => !taken.has(p.toLowerCase()) && p.toLowerCase().includes(query))
            .sort((a, b) => Number(!a.toLowerCase().startsWith(query)) - Number(!b.toLowerCase().startsWith(query)))
            .slice(0, 8);
        list.innerHTML = items.map((p, i) => `<li data-i="${i}" class="${i === active ? 'active' : ''}">${p}</li>`).join('');
        list.hidden = !items.length;
    }

    function pick(place) {
        const head = parts().slice(0, -1).map((s) => s.trim()).filter(Boolean);
        input.value = [...head, place].join(', ') + ', ';
        syncClear();
        render();
        input.focus();
    }

    input.addEventListener('focus', render);
    input.addEventListener('input', () => { active = -1; syncClear(); render(); });
    input.addEventListener('keydown', (e) => {
        if (list.hidden) return;
        if (e.key === 'ArrowDown') { e.preventDefault(); active = (active + 1) % items.length; render(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); active = (active - 1 + items.length) % items.length; render(); }
        else if (e.key === 'Enter' && active >= 0) { e.preventDefault(); pick(items[active]); }
        else if (e.key === 'Escape') close();
    });
    // mousedown (not click) so it fires before the input loses focus.
    list.addEventListener('mousedown', (e) => {
        const li = e.target.closest('li');
        if (li) { e.preventDefault(); pick(items[Number(li.dataset.i)]); }
    });
    clearBtn.addEventListener('click', (e) => {
        e.preventDefault();
        input.value = '';
        syncClear();
        render();
        input.focus();
    });
    input.addEventListener('blur', () => setTimeout(close, 120));
    syncClear();
    return syncClear; // call after setting input.value programmatically
}
