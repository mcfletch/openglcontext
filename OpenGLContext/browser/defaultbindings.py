from OpenGLContext.browser import confignodes

confignodes.KeyboardEventBinding(
    name = '<up>',
    state = 1,
    modifiers = ['alt'],
    method = 'up',
    targetKey = 'context',
)
confignodes.KeyboardEventBinding(
    name = '<up>',
    state = 1,
    modifiers = ['ctrl'],
    method = 'turnup',
    targetKey = 'context',
)
confignodes.KeyboardEventBinding(
    name = '<down>',
    state = 1,
    modifiers = [],
    method = 'backward',
    targetKey = 'context',
)
confignodes.KeyboardEventBinding(
    name = '<down>',
    state = 1,
    modifiers = ['alt'],
    method = 'down',
    targetKey = 'context',
)
confignodes.KeyboardEventBinding(
    name = '<down>',
    state = 1,
    modifiers = ['ctrl'],
    method = 'turndown',
    targetKey = 'context',
)
confignodes.KeyboardEventBinding(
    name = '<left>',
    state = 1,
    modifiers = [],
    method = 'turnleft',
    targetKey = 'context',
)
confignodes.KeyboardEventBinding(
    name = '<left>',
    state = 1,
    modifiers = ['alt'],
    method = 'left',
    targetKey = 'context',
)
confignodes.KeyboardEventBinding(
    name = '<right>',
    state = 1,
    modifiers = [],
    method = 'turnright',
    targetKey = 'context',
)
confignodes.KeyboardEventBinding(
    name = '<right>',
    state = 1,
    modifiers = ['alt'],
    method = 'right',
    targetKey = 'context',
)
confignodes.KeypressEventBinding(
    name = '-',
    modifiers = [],
    method = 'straighten',
    targetKey = 'context',
)