def addEventHandler( type, name, modifiers, function, state=1 ):
    modifiers = [i[0] for i in map( None, ('shift','ctrl','alt'), modifiers ) if i[1]]
    typeCap = type.capitalize()
    if type == 'keyboard':
        stateLine = """state = %(state)r,"""%locals()
    else:
        stateLine = ""
    print """%(typeCap)sEventBinding(
    name = %(name)r,
    %(stateLine)s
    modifiers = %(modifiers)s,
    method = %(function)r,
    targetKey = 'context',
)"""%locals()

addEventHandler( 'keyboard', name='<up>', state=1, modifiers=(0,0,1), function="up" )
addEventHandler( 'keyboard', name='<up>', state=1, modifiers=(0,1,0), function="turnup")
addEventHandler( 'keyboard', name='<down>', state=1, modifiers=(0,0,0), function="backward" )
addEventHandler( 'keyboard', name='<down>', state=1, modifiers=(0,0,1), function="down" )
addEventHandler( 'keyboard', name='<down>', state=1, modifiers=(0,1,0), function="turndown")
        
addEventHandler( 'keyboard', name='<left>', state=1, modifiers=(0,0,0), function="turnleft")
addEventHandler( 'keyboard', name='<left>', state=1, modifiers=(0,0,1), function="left")
addEventHandler( 'keyboard', name='<right>', state=1, modifiers=(0,0,0), function="turnright")
addEventHandler( 'keyboard', name='<right>', state=1, modifiers=(0,0,1), function="right")
        
addEventHandler( 'keypress', name='-', modifiers=(0,0,0), function="straighten")

##addEventHandler( 'mousebutton', button=0, state = 1, modifiers=(0,0,1), function="startExamineMode")
