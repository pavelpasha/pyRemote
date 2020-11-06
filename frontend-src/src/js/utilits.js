// <Helpers>
export function formatMacString(mac_integer) {
    return new Array(6).join('00') // '000000000000'
        .match(/../g) // [ '00', '00', '00', '00', '00', '00' ]
        .concat(
            mac_integer.toString(16) // "4a8926c44578"
            .match(/.{1,2}/g) // ["4a", "89", "26", "c4", "45", "78"]
        ) // ["00", "00", "00", "00", "00", "00", "4a", "89", "26", "c4", "45", "78"]
        .reverse() // ["78", "45", "c4", "26", "89", "4a", "00", "00", "00", "00", "00", "00", ]
        .slice(0, 6)
        .reverse() // ["78", "45", "c4", "26", "89", "4a" ]
        .join(':').toUpperCase();
}

/*
    Convert seconds from Epoch to Date object
    @secs {int}
    @return {Date}
*/
export function toDateTime(secs) {
    let t = new Date(1970, 0, 1); // Epoch
    t.setSeconds(secs);
    return t;
}

export function dateFormat(date_string) {
    let date = toDateTime(date_string);
    let timeOffsetInMS = date.getTimezoneOffset() * 60000;
    date.setTime(date.getTime() - timeOffsetInMS);
    let options = {
        year: 'numeric',
        month: 'numeric',
        day: 'numeric',
        timezone: 'Moskow',
        hour: 'numeric',
        minute: 'numeric',
        second: 'numeric',
        hour12: false,
    };
    return date.toLocaleDateString('en-US', options);

}

 export function notify (text, type) {
    if (!["success", "error", "info"].includes(type))
        type = "info";

    let wrapper = document.createElement('div');
    wrapper.className = `notification ${type}`;
    wrapper.innerHTML = text;
    document.body.appendChild(wrapper);
    setTimeout(() => document.body.removeChild(wrapper), 2000);
}

/*
    Simple utility. Creates a new DOM Element with given classname, id and attributes. 
    @tag {string} A tag of Element
    @parent? {Element} The element to which the created element will be appended as child (Optional)
    @classname? {string} A desired class name of element (Optional)
    @id? {string} A desired id of element (Optional)
    @attributes? {Dictionary {string:string}} A list of html attributes, which be applyed to created element (Optional)
    @return {Element} The created element
*/
export function createDOMElement(tag, parent = null, classname = null, id = null, attributes = null) {

    let el = document.createElement(tag);
    if (!el)
        return null;
    if (classname)
        el.className = classname;
    if (id)
        el.id = id;
    if (attributes) {
        for (var key in attributes) {
            // check if the property/key is defined in the object itself, not in parent
            if (attributes.hasOwnProperty(key)) {
                el.setAttribute(key, attributes[key]);
            }
        }
    }
    if ((parent instanceof Element || parent instanceof HTMLDocument) && parent)
        return parent.appendChild(el);
    return el;
}


// </Helpers>