from expipe_plugin_cinpla.imports import *
from expipe_plugin_cinpla.tools.action import generate_templates, get_git_info, query_yes_no
from expipe_plugin_cinpla.tools import config


def attach_to_cli(cli):
    @cli.command('list')
    @click.argument('what', type=click.Choice(['dir', 'actions']))
    def generate_notebook(what):
        project = expipe.get_project(PAR.USER_PARAMS['project_id'])
        path = os.path.join(expipe.settings['data_path'],
                       PAR.USER_PARAMS['project_id'])
        if what == 'dir':
            pprint.pprint(os.listdir(path))
        elif what == 'actions':
            pprint.pprint(project.actions.keys())

    @cli.command('annotate', short_help='Parse info about recorded units')
    @click.argument('action-id', type=click.STRING)
    @click.option('-t', '--tag',
                    multiple=True,
                    type=click.STRING,
                    callback=config.optional_choice,
                    envvar=PAR.POSSIBLE_TAGS,
                    help='Add tags to action.',
                    )
    @click.option('--message', '-m',
                  multiple=True,
                  type=click.STRING,
                  help='Add message, use "text here" for sentences.',
                  )
    @click.option('-u', '--user',
                  type=click.STRING,
                  help='The experimenter performing the annotation.',
                  )
    def annotate(action_id, tag, message, user):
        project = expipe.get_project(PAR.USER_PARAMS['project_id'])
        action = project.require_action(action_id)
        user = user or PAR.USER_PARAMS['user_name']
        user = user or []
        if len(user) == 0:
            raise ValueError('Please add user name')

        users = list(set(action.users))
        if user not in users:
            users.append(user)
        action.users = users
        action.messages.extend([{'message': m,
                                 'user': user,
                                 'datetime': datetime.now()}
                               for m in message])
        action.tags.extend(tag)

    @cli.command('adjust',
                 short_help='Parse info about drive depth adjustment')
    @click.argument('subject-id',  type=click.STRING)
    @click.option('-d', '--date',
                  type=click.STRING,
                  help=('The date of the surgery format: "dd.mm.yyyyTHH:MM" ' +
                        'or "now".'),
                  )
    @click.option('-a', '--adjustment',
                  multiple=True,
                  callback=config.validate_adjustment,
                  help=('The adjustment amount on given anatomical location ' +
                        'given as <key num value unit>'),
                  )
    @click.option('--overwrite',
                  is_flag=True,
                  help='Overwrite modules or not.',
                  )
    @click.option('--index',
                  type=click.INT,
                  help=('Index for module name, this is found automatically ' +
                        'by default.'),
                  )
    @click.option('--init',
                  is_flag=True,
                  help='Initialize, retrieve depth from surgery.',
                  )
    @click.option('-u', '--user',
                  type=click.STRING,
                  help='The experimenter performing the adjustment.',
                  )
    @click.option('-y', '--yes',
                  is_flag=True,
                  help='No query for correct adjustment.',
                  )
    def generate_adjustment(subject_id, date, adjustment, user, index, init,
                            overwrite, yes):
        if not init:
            assert len(adjustment) != 0, 'Missing option "-a" / "--adjustment".'
            assert date is not None, 'Missing option "-d" / "--date".'
        if init and date is None:
            date = 'now'
        DTIME_FORMAT = expipe.io.core.datetime_format
        if date == 'now':
            date = datetime.now()
        else:
            date = datetime.strptime(date, '%d.%m.%YT%H:%M')
        datestring = datetime.strftime(date, DTIME_FORMAT)
        project = expipe.get_project(PAR.USER_PARAMS['project_id'])
        if init:
            action = project.require_action(subject_id + '-adjustment')
        else:
            action = project.get_action(subject_id + '-adjustment')
        if index is None and not init:
            deltas = []
            for name in action.modules.keys():
                if name.endswith('adjustment'):
                    deltas.append(int(name.split('_')[0]))
            index = max(deltas) + 1
        if init:
            index = 0
            surgery = project.get_action(subject_id + '-surgery-implantation')
            sdict = surgery.modules.to_dict()
            templates_used = {
                key: mod for key, mod in PAR.MODULES['implantation'].items()
                if mod in sdict}
            prev_depth = {key: {pos_key: sdict[mod][pos_key][2]
                                for pos_key in sdict[mod]
                                if pos_key.startswith('position_')
                                and pos_key.split('_')[-1].isnumeric()}
                          for key, mod in templates_used.items()}
            for key, groups in prev_depth.items():
                for group, depth in groups.items():
                    if not isinstance(depth, pq.Quantity):
                        raise ValueError('Depth of implant ' +
                                         '"{} {} = {}"'.format(key, group, depth) +
                                         ' not recognized')
                    prev_depth[key][group] = depth.astype(float)
        else:
            prev_name = '{:03d}_adjustment'.format(index - 1)
            prev_depth = action.require_module(name=prev_name).to_dict()['depth']
        name = '{:03d}_adjustment'.format(index)
        assert isinstance(prev_depth, dict), 'Unable to retrieve previous depth.'
        adjustment_dict = {key: dict() for key in prev_depth}
        for key, num, val, unit in adjustment:
            pos_key = 'position_{}'.format(num)
            adjustment_dict[key][pos_key] = pq.Quantity(val, unit)
        adjustment = {key: {pos_key: adjustment_dict[key].get(pos_key) or 0 * pq.mm
                            for pos_key in prev_depth[key]}
                      for key in prev_depth}
        curr_depth = {key: {pos_key: round(prev_depth[key][pos_key] + val[pos_key], 3)
                            for pos_key in val}
                      for key, val in adjustment.items()} # round to um

        def last_num(x):
            return '%.3d' % int(x.split('_')[-1])
        correct = query_yes_no(
            'Correct adjustment?: \n' +
            ' '.join('{} {} = {}\n'.format(key, pos_key, val[pos_key])
                     for key, val in adjustment.items()
                     for pos_key in sorted(val, key=lambda x: last_num(x))) +
            'New depth: \n' +
            ' '.join('{} {} = {}\n'.format(key, pos_key, val[pos_key])
                     for key, val in curr_depth.items()
                     for pos_key in sorted(val, key=lambda x: last_num(x))),
            answer=yes
        )
        if not correct:
            print('Aborting adjustment.')
            return
        print(
            'Registering adjustment: \n' +
            ' '.join('{} {} = {}\n'.format(key, pos_key, val[pos_key])
                     for key, val in adjustment.items()
                     for pos_key in sorted(val, key=lambda x: last_num(x))) +
            ' New depth: \n' +
            ' '.join('{} {} = {}\n'.format(key, pos_key, val[pos_key])
                     for key, val in curr_depth.items()
                     for pos_key in sorted(val, key=lambda x: last_num(x)))
        )
        template_name = PAR.TEMPLATES.get('adjustment') or 'protocol_depth_adjustment'
        module = action.require_module(template=template_name,
                                       name=name, overwrite=overwrite)
        content = module.to_dict()
        content['depth'] = curr_depth
        content['adjustment'] = adjustment
        content['experimenter'] = user
        content['date'] = datestring
        content['git_note'] = get_git_info()
        action.require_module(name=name, contents=content, overwrite=True)

        action.type = 'Adjustment'
        action.subjects = [subject_id]
        user = user or PAR.USER_PARAMS['user_name']
        user = user or []
        if len(user) == 0:
            raise ValueError('Please add user name')
        action.users = [user]

    @cli.command('register-surgery', short_help='Generate a surgery action.')
    @click.argument('subject-id')
    @click.option('--date', '-d',
                  required=True,
                  type=click.STRING,
                  help='The date of the surgery format: "dd.mm.yyyyTHH:MM".',
                  )
    @click.option('-t', '--tag',
                  multiple=True,
                  type=click.STRING,
                  callback=config.optional_choice,
                  envvar=PAR.POSSIBLE_TAGS,
                  help='Add tags to action.',
                  )
    @click.option('--procedure',
                  required=True,
                  type=click.Choice(['implantation', 'injection']),
                  help='The type of surgery "implantation" or "injection".',
                  )
    @click.option('--overwrite',
                  is_flag=True,
                  help='Overwrite modules or not.',
                  )
    @click.option('--hard',
                  is_flag=True,
                  help='Overwrite by deleting action.',
                  )
    @click.option('-u', '--user',
                  type=click.STRING,
                  help='The experimenter performing the surgery.',
                  )
    @click.option('-w', '--weight',
                  nargs=2,
                  type=(click.FLOAT, click.STRING),
                  default=(None, None),
                  help='The weight of the subject with unit i.e. <200 g> (ommit <>).',
                  )
    @click.option('-p', '--position',
                  required=True,
                  multiple=True,
                  callback=config.validate_position,
                  help='The position e.g. <"mecl 0 x y z mm"> (ommit <>).',
                  )
    @click.option('-a', '--angle',
                  required=True,
                  multiple=True,
                  callback=config.validate_angle,
                  help='The angle of implantation/injection.',
                  )
    @click.option('--message', '-m',
                  multiple=True,
                  type=click.STRING,
                  help='Add message, use "text here" for sentences.',
                  )
    def generate_surgery(subject_id, procedure, date, user, weight, hard,
                         overwrite, position, angle, message, tag):
        # TODO tag sucject as active
        assert weight != (None, None), 'Missing argument -w / --weight.'
        weight = pq.Quantity(weight[0], weight[1])
        project = expipe.require_project(PAR.USER_PARAMS['project_id'])
        action = project.require_action(subject_id + '-surgery-' + procedure)
        if overwrite and hard:
            project.delete_action(subject_id + '-surgery-' + procedure)
        generate_templates(action, 'surgery_' + procedure,
                           overwrite, git_note=get_git_info())
        if date == 'now':
            date = datetime.now()
        else:
            date = datetime.strptime(date, '%d.%m.%YT%H:%M')
        action.datetime = date
        action.location = 'Sterile surgery station'
        action.type = 'Surgery'
        action.tags = [procedure] + list(tag)
        action.subjects = [subject_id]
        user = user or PAR.USER_PARAMS['user_name']
        user = user or []
        if len(user) == 0:
            raise ValueError('Please add user name')
        print('Registering user ' + user)
        action.users = [user]
        if overwrite:
            action.messages = []
        action.messages.extend([{'message': m,
                                 'user': user,
                                 'datetime': datetime.now()}
                               for m in message])
        modules_dict = action.modules.to_dict()
        keys = list(set([pos[0] for pos in position]))
        modules = {
            key: action.require_module(template=PAR.MODULES[procedure][key],
                                       overwrite=overwrite).to_dict()
            for key in keys}
        for key, num, x, y, z, unit in position:
            mod = modules[key]
            if 'position' in mod:
                del(mod['position']) # delete position template
            print('Registering position ' +
                  '{} {}: x={}, y={}, z={} {}'.format(key, num, x, y, z, unit))
            mod['position_{}'.format(num)] = pq.Quantity([x, y, z], unit)
        for key, ang, unit in angle:
            mod = modules[key]
            if 'angle' in mod:
                del(mod['angle']) # delete position template
            print('Registering angle ' +
                  '{}: angle={} {}'.format(key, ang, unit))
            mod['angle'] = pq.Quantity(ang, unit)
        for key in keys:
            action.require_module(name=PAR.MODULES[procedure][key],
                                  contents=modules[key], overwrite=True)

        subject = {'_inherits': '/action_modules/' +
                                'subjects-registry/' +
                                subject_id}
        subject['weight'] = weight
        action.require_module(name=PAR.MODULES['subject'], contents=subject,
                              overwrite=True)
        subjects_project = expipe.require_project('subjects-registry')
        subject_action = subjects_project.require_action(subject_id)
        subject_action.tags.extend(['surgery', PAR.USER_PARAMS['project_id']])
        subject_action.users.append(user)

    @cli.command('register-subject',
                 short_help=('Register a subject to the "subjects-registry" ' +
                             'project.'))
    @click.argument('subject-id')
    @click.option('--overwrite',
                  is_flag=True,
                  help='Overwrite modules or not.',
                  )
    @click.option('-u', '--user',
                  type=click.STRING,
                  help='The experimenter performing the registration.',
                  )
    @click.option('--location',
                  required=True,
                  type=click.STRING,
                  help='The location of the animal.',
                  )
    @click.option('--birthday',
                  required=True,
                  type=click.STRING,
                  help='The birthday of the subject, format: "dd.mm.yyyy".',
                  )
    @click.option('--cell_line',
                  type=click.STRING,
                  callback=config.optional_choice,
                  envvar=PAR.POSSIBLE_CELL_LINES,
                  help='Add tags to action.',
                  )
    @click.option('--developmental_stage',
                  type=click.STRING,
                  help="The developemtal stage of the subject. E.g. 'embroyonal', 'adult', 'larval' etc.",
                  )
    @click.option('--gender',
                  type=click.STRING,
                  help='Male or female?',
                  )
    @click.option('--genus',
                  type=click.STRING,
                  help='The Genus of the studied subject. E.g "rattus"',
                  )
    @click.option('--health_status',
                  type=click.STRING,
                  help='Information about the health status of this subject.',
                  )
    @click.option('--label',
                  type=click.STRING,
                  help='If the subject has been labled in a specific way. The lable can be described here.',
                  )
    @click.option('--population',
                  type=click.STRING,
                  help='The population this subject is offspring of. This may be the bee hive, the ant colony, etc.',
                  )
    @click.option('--species',
                  type=click.STRING,
                  help='The scientific name of the species e.g. Apis mellifera, Homo sapiens.',
                  )
    @click.option('--strain',
                  type=click.STRING,
                  help='The strain the subject was taken from. E.g. a specific genetic variation etc.',
                  )
    @click.option('--trivial_name',
                  type=click.STRING,
                  help='The trivial name of the species like Honeybee, Human.',
                  )
    @click.option('--weight',
                  nargs=2,
                  type=(click.FLOAT, click.STRING),
                  default=(None, None),
                  help='The weight of the animal.',
                  )
    @click.option('--message', '-m',
                  multiple=True,
                  type=click.STRING,
                  help='Add message, use "text here" for sentences.',
                  )
    @click.option('-t', '--tag',
                  multiple=True,
                  type=click.STRING,
                  callback=config.optional_choice,
                  envvar=PAR.POSSIBLE_TAGS,
                  help='Add tags to action.',
                  )
    def generate_subject(subject_id, overwrite, user, message, location, tag,
                         **kwargs):
        DTIME_FORMAT = expipe.io.core.datetime_format
        project = expipe.require_project('subjects-registry')
        action = project.require_action(subject_id)
        kwargs['birthday'] = datetime.strftime(
            datetime.strptime(kwargs['birthday'], '%d.%m.%Y'), DTIME_FORMAT)
        action.datetime = datetime.now()
        action.type = 'Info'
        action.tags.extend(list(tag))
        action.location = location
        action.subjects = [subject_id]
        user = user or PAR.USER_PARAMS['user_name']
        user = user or []
        if len(user) == 0:
            raise ValueError('Please add user name')
        print('Registering user ' + user)
        action.users = [user]
        action.messages.extend([{'message': m,
                                 'user': user,
                                 'datetime': datetime.now()}
                               for m in message])
        subject_template_name = PAR.MODULES.get('subject') or 'subject_subject'
        subject = action.require_module(template=subject_template_name,
                                        overwrite=overwrite).to_dict()
        for key, val in kwargs.items():
            if isinstance(val, (str, float, int)):
                subject[key]['value'] = val
            elif isinstance(val, tuple):
                if not None in val:
                    subject[key] = pq.Quantity(val[0], val[1])
            elif isinstance(val, type(None)):
                pass
            else:
                raise TypeError('Not recognized type ' + str(type(val)))
        not_reg_keys = []
        for key, val in subject.items():
            if isinstance(val, dict):
                if val.get('value') is None:
                    not_reg_keys.append(key)
                elif len(val.get('value')) == 0:
                    not_reg_keys.append(key)
        if len(not_reg_keys) > 0:
            warnings.warn('No value registered for {}'.format(not_reg_keys))
        action.require_module(name=subject_template_name, contents=subject,
                              overwrite=True)

    @cli.command('register-euthanasia',
                 short_help=('Register a subjects euthanasia.'))
    @click.argument('subject-id')
    @click.option('-u', '--user',
                  type=click.STRING,
                  help='The experimenter performing the registration.',
                  )
    @click.option('--message', '-m',
                  multiple=True,
                  type=click.STRING,
                  help='Add message, use "text here" for sentences.',
                  )
    def generate_euthanasia(subject_id, user, message):
        project = expipe.require_project('subjects-registry')
        action = project.require_action(subject_id)
        action.tags.append('euthanised')
        assert action.subjects[0] == subject_id
        user = user or PAR.USER_PARAMS['user_name']
        user = user or []
        if len(user) == 0:
            raise ValueError('Please add user name')
        print('Registering user ' + user)
        action.users.append(user)
        action.messages.extend([{'message': m,
                                 'user': user,
                                 'datetime': datetime.now()}
                               for m in message])

    @cli.command('register-perfusion',
                 short_help=('Generate a perfusion action. ' +
                             'Also tags the subject as perfused and euthanised.'))
    @click.argument('subject-id')
    @click.option('--date', '-d',
                  required=True,
                  type=click.STRING,
                  help='The date of the surgery format: "dd.mm.yyyyTHH:MM".',
                  )
    @click.option('--overwrite',
                  is_flag=True,
                  help='Overwrite modules or not.',
                  )
    @click.option('-u', '--user',
                  type=click.STRING,
                  help='The experimenter performing the surgery.',
                  )
    @click.option('--weight',
                  nargs=2,
                  type=(click.FLOAT, click.STRING),
                  default=(None, None),
                  help='The weight of the animal.',
                  )
    def generate_perfusion(subject_id, date, user, overwrite, weight):
        project = expipe.get_project(PAR.USER_PARAMS['project_id'])
        action = project.require_action(subject_id + '-perfusion')
        generate_templates(action, 'perfusion',
                           overwrite, git_note=get_git_info())
        if date == 'now':
            date = datetime.now()
        else:
            date = datetime.strptime(date, '%d.%m.%YT%H:%M')
        action.datetime = date
        action.location = 'Sterile surgery station'
        action.type = 'Surgery'
        action.tags = ['perfusion']
        action.subjects = [subject_id]
        user = user or PAR.USER_PARAMS['user_name']
        user = user or []
        if len(user) == 0:
            raise ValueError('Please add user name')
        print('Registering user ' + user)
        action.users = [user]
        subject = {'_inherits': '/action_modules/' +
                                'subjects-registry/' +
                                subject_id}
        if weight != (None, None):
            subject['weight'] = pq.Quantity(weight[0], weight[1])
        action.require_module(name=PAR.MODULES['subject'], contents=subject,
                              overwrite=True)
        subjects_project = expipe.require_project('subjects-registry')
        subject_action = subjects_project.require_action(subject_id)
        subject_action.tags.extend(['perfused', 'euthanised'])