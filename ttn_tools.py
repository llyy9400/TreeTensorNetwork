import numpy as np
import torch
import time
import opt_einsum as oe
import scipy.sparse as spl
import scipy.sparse.linalg as sl
import pickle
import os
import itertools as it
import functools
import gc

################################################################################
# TOOLS FOR TTN file                                                           #
################################################################################

# TODO:
# Entire file: add docstrings

torch.set_printoptions(10)

def timer(func):
    """ Wrapper for store_time method of class TreeTensorNetwork, times optimization
        of a single tensor (Environments + SVD)"""
    @functools.wraps(func)
    def f(*args, **kwargs):
        before = time.time()
        rv = func(*args, **kwargs)
        after = time.time()
        args[0].store_time(after - before)
        # print(after-before)
        return rv
    return f


def store_network(tree_object, folder_to_store, ham_name):
    """ Stores network in folder 'stored_networks/hamiltonian' where hamiltonian can differ
    per class instance of Do_experiment'"""
    temp_folder = folder_to_store
    temp_folder += '/' + ham_name
    if not os.path.exists(temp_folder):
        os.makedirs(temp_folder)

    network_folder = temp_folder + '/'
    if not os.path.exists(network_folder):
        os.makedirs(network_folder)

    file_name = tree_object.file_name+'.pickle'
    file_name = temp_folder+'/'+file_name

    with open(file_name, 'wb') as data:
        pickle.dump(tree_object, data)
    print('Network stored in %s as %s'%(network_folder, tree_object.file_name+'.pickle'))


def load_network(folder_to_check, ham_name, network_name, print_load=True):
    if type(network_name) != str:
        raise TypeError('path is not of type string')

    elif not os.path.exists(folder_to_check+'/'+ham_name):
        raise FileNotFoundError('No folder %s found '%(ham_name))
    elif os.path.exists(folder_to_check+'/'+ham_name) and not os.path.exists(folder_to_check+'/'+ham_name+'/'+network_name):
        raise FileNotFoundError('No file %s found in folder %s'%(network_name, ham_name))
    else:
        path_to_network = folder_to_check+'/'+ham_name+'/'+network_name
        with open(path_to_network, 'rb') as data:
            tree_object = pickle.load(data)
        if print_load:
            print('Network %s loaded'%(tree_object.file_name))
        return tree_object


def create_cache_tensor(*dims, ttype, backend='torch'):
    for i in dims:
        if type(i) == float:
            print(i, type(i))
            print("type is not int m8")
            raise TypeError
    if backend == 'torch':
        tens = torch.zeros(*dims, dtype=ttype, device='cuda:0')
    elif backend == 'numpy':
        tens = np.zeros(dims)
    return tens


def create_tensor(*dims, ttype, backend='torch'):
    for i in dims:
        if type(i) == float:
            print(i, type(i))
            print("type is not int m8")
            raise TypeError
    if backend == 'torch':
        tens = torch.rand(*dims, dtype=ttype, device='cuda:0')
        tens = tens.T.svd(some=True)[0]
        tens = tens.T.reshape(*dims)
    elif backend == 'numpy':
        tens = np.random.rand(*dims)
        tens = np.linalg.svd(tens, full_matrices = False)[-1]
    return tens


def create_sym_tensor(*dims, ttype, backend='torch'):
    """ docstring for create_sym_tensor """
    for i in dims:
        if type(i) == float:
            print(i, type(i))
            print("type is not int m8")
            raise TypeError

    if backend=='cupy':
        # print(cp.cuda.get_device_id())
        tens = cp.random.uniform(-1,1, size=[*dims])
        tens = tens+cp.transpose(tens,(0,2,1))
        tens = cp.linalg.svd(tens.reshape(dims[0], dims[1]**2), full_matrices=False)[-1]
        tens = tens.reshape(*dims)

    elif backend=='torch':
        # so random_(0,1) just fills the tensor with 1 1 and the rest 0:
        # resulted in a "bug" where by accidant ising worked but heisenberg did not
        # anyhow, it is fixed now...
        tens = torch.ones(*dims, dtype = ttype, device='cuda:0').random_(0,10)

        tens.add_(tens.transpose(2,1))
        # transpose is need, for explanation see:
        # https://github.com/pytorch/pytorch/issues/24900
        tens = tens.reshape(dims[0],dims[1]*dims[1]).T
        u, s, v = tens.svd(some=True)
        tens = u.T.reshape(*dims)
        # print(tens)
        # return tens

    elif backend=='numpy':
        tens = np.random.uniform(0,10,[*dims])
        tens = tens + np.transpose(tens, (0, 2, 1))
        tens = np.linalg.svd(tens.reshape(dims[0],dims[1]**2), full_matrices=False)[-1]
        tens = tens.reshape(*dims)
        print(tens)
    else:
        tens=None

    return tens


def get_bonds(lattice, sub_lattice, spacings):
    """ docstring for get_bonds """

    left_boundaries = {i:[] for i in spacings}
    lower_boundaries = {i:[] for i in spacings}
    vertical_inner_bonds = {i:[] for i in spacings}
    horizontal_inner_bonds = {i:[] for i in spacings}
    single_sites = {0:[]}

    for space in spacings:
        linear_size = lattice.shape[0]
        for i in sub_lattice.flatten():
            locations = np.where(lattice==i)
            m, n = *locations[0], *locations[1]
            original_location = lattice[m,n]
            # nearest-neighbour bonds
            if space != 1.5 and (space>0):
                if (lattice[m,(n-int(space))%linear_size] not in sub_lattice):
                    left_boundaries[space].append([original_location,
                                lattice[m,(n-int(space))%linear_size]][::-1])
                if (lattice[(m+int(space))%linear_size, n] not in sub_lattice):
                    lower_boundaries[space].append([original_location,
                                lattice[(m+int(space))%linear_size, n]][::-1])

                horizontal_inner_bonds[space].append([original_location, lattice[m, (n+int(space))%linear_size]])
                vertical_inner_bonds[space].append([original_location, lattice[(m-int(space))%linear_size,n]])
            # next-nearest-neighbour bonds
                # single_sites.append([original_location])
            if space == 1.5:
                if (lattice[(m-int(space))%linear_size,(n-int(space))%linear_size] not in sub_lattice):
                    left_boundaries[space].append([original_location,
                                lattice[(m-int(space))%linear_size,(n-int(space))%linear_size]][::-1])
                if (lattice[(m+int(space))%linear_size, (n-int(space))%linear_size] not in sub_lattice):
                    lower_boundaries[space].append([original_location,
                                lattice[(m+int(space))%linear_size, (n-int(space))%linear_size]][::-1])
                horizontal_inner_bonds[space].append([original_location,
                                lattice[(m+int(space))%linear_size, (n+int(space))%linear_size]])
                vertical_inner_bonds[space].append([original_location,
                                lattice[(m-int(space))%linear_size,(n+int(space))%linear_size]])
            if (space == 0) or (space == 0.0):
                single_sites[space].append([original_location])

            # elif space == 0:
    return (horizontal_inner_bonds, vertical_inner_bonds, single_sites, lower_boundaries,
        left_boundaries)


def get_single_network(list_of_nodes, bondtype, bond):
    """ Docstring for get_single_network """
    temporary_network = []
    # if (5 in bond) and (1 in bond):
    if len(bond) == 2:
        for a_node in list_of_nodes:
            for a_bond in a_node.vertical_two_site_terms[bondtype]:
                if (a_bond[1] == bond[1]) and (a_bond[0] == bond[0]):
                    temporary_network.append(a_node)
            for a_bond in a_node.horizontal_two_site_terms[bondtype]:
                if (a_bond[1] == bond[1]) and (a_bond[0] == bond[0]):
                    temporary_network.append(a_node)
            for a_bond in a_node.vertical_bc_terms[bondtype]:
                if (a_bond[1] == bond[1]) and (a_bond[0] == bond[0]):
                    temporary_network.append(a_node)
            for a_bond in a_node.horizontal_bc_terms[bondtype]:
                if (a_bond[1] == bond[1]) and (a_bond[0] == bond[0]):
                    temporary_network.append(a_node)
    if len(bond) == 1:
        for a_node in list_of_nodes:
            if any(a_bond[0] == bond[0] for a_bond in a_node.one_site_terms[bondtype]):
                temporary_network.append(a_node)
    temporary_network = list(set(temporary_network))
    temporary_network.sort(key=lambda x: x.layer)

    return {'bond':  bond, 'bondspace': bondtype, 'temporary_network': temporary_network}


def get_legs(cut, node, network):
    """ Docstring for get_legs() """

    for current_network in network:
        bond = current_network['bond']

        tensors_to_loop_over = current_network['temporary_network']
        # maybe add sort of tensors_to_loop_over over here, first value,
        # then layer
        max_leg = None
        environment_legs = None
        operator_legs = []
        all_legs = []
        current_value = node.value
        tensors_to_loop_over.sort(key = lambda x: x.layer)

        for current_node in tensors_to_loop_over:
            if current_node.isRoot():
                current_node.bralegs = np.array([1, 2, 3])
                current_node.ketlegs = np.array([1, None, None])
                if current_node.left in tensors_to_loop_over and not current_node.right in tensors_to_loop_over:
                    current_node.ketlegs[2] = current_node.bralegs[2]
                elif current_node.right in tensors_to_loop_over and not current_node.left in tensors_to_loop_over:
                    current_node.ketlegs[1] = current_node.bralegs[1]

                mask_legs = np.where(current_node.ketlegs == None)[0]
                new_values = np.arange(np.max(current_node.bralegs)+1,
                    np.max(current_node.bralegs)+mask_legs.size+1)
                current_node.ketlegs[mask_legs] = new_values
                max_leg =  np.max(np.array([np.max(current_node.ketlegs), np.max(current_node.bralegs)]))

            if not current_node.isRoot():
                # print(current_node.value, current_node.current_tensor)
                current_node.bralegs = [None]*len(current_node.current_tensor.shape)
                current_node.ketlegs = [None]*len(current_node.current_tensor.shape)

                current_node.bralegs, current_node.ketlegs = np.array(current_node.bralegs), np.array(current_node.ketlegs)
                if current_node.isLeftChild():
                    current_node.bralegs[0] = current_node.parent.bralegs[1]
                    current_node.ketlegs[0] = current_node.parent.ketlegs[1]
                if current_node.isRightChild():
                    current_node.bralegs[0] = current_node.parent.bralegs[2]
                    current_node.ketlegs[0] = current_node.parent.ketlegs[2]
                if current_node.layer != cut:
                    mask_legs = np.where(current_node.bralegs == None)[0]
                    new_bralegs = np.arange(max_leg+1, max_leg+mask_legs.size+1)
                    current_node.bralegs[mask_legs] = new_bralegs
                    max_leg = np.max(current_node.bralegs)

                # below is for lower legs of a node
                if current_node.left in tensors_to_loop_over and current_node.right in tensors_to_loop_over:
                    mask_legs = np.where(current_node.ketlegs == None)[0]
                    current_node.ketlegs[mask_legs] = np.arange(max_leg+1, max_leg+mask_legs.size+1)
                    max_leg = np.max(current_node.ketlegs)

                elif current_node.left in tensors_to_loop_over and not current_node.right in tensors_to_loop_over:
                    current_node.ketlegs[2] = current_node.bralegs[2]
                    current_node.ketlegs[1] = max_leg+1
                    max_leg = np.max(current_node.ketlegs)

                elif current_node.right in tensors_to_loop_over and not current_node.left in tensors_to_loop_over:
                    current_node.ketlegs[1] = current_node.bralegs[1]
                    current_node.ketlegs[2] = max_leg+1
                    max_leg = np.max(current_node.ketlegs)

                elif not current_node.left in tensors_to_loop_over and not current_node.right in tensors_to_loop_over:
                    current_node.bralegs = np.concatenate(([current_node.bralegs[0]], np.arange(max_leg+1, max_leg+len(current_node.current_tensor.shape))))
                    max_leg = np.max(current_node.bralegs)
                    current_node.ketlegs = np.concatenate(([current_node.ketlegs[0]], current_node.bralegs[1:]))

                    for j in bond:
                        mask_site = np.where(current_node.lattice.flatten() == j)[0]+1
                        # print(mask_site)
                        if mask_site.size>0:
                            current_node.ketlegs[mask_site] = max_leg+1
                            operator_legs.append(np.array([current_node.bralegs[mask_site][0], max_leg+1]))
                            max_leg = np.max(current_node.ketlegs)

                try:
                    max_leg = np.max(np.array([np.max(current_node.ketlegs), np.max(current_node.bralegs)]))
                except TypeError:
                    print('Whoopsie, you tried to operate on a NoneType. Pls stahp')

            if current_node.value == current_value:
                environment_legs = current_node.bralegs
            all_legs.extend((current_node.bralegs,current_node.ketlegs))
            # if node.isRoot():
            #     print(operator_legs, bond)

        # if reverse_bool:
        #     operator_legs = operator_legs[::-1]
        all_legs.extend(operator_legs[:])
        copy_shape = []
        current_network['full_legs'] = all_legs
        for i in all_legs:
            copy_shape.append(i.shape[0])

        copylegs = np.hstack(all_legs)
        open_legs = np.arange(1, len(current_node.current_tensor.shape)+1, dtype = 'int')*-1

        for i, env_leg_i in enumerate(environment_legs):
            new_open_legs_mask = np.where(copylegs == env_leg_i)[0]
            copylegs[new_open_legs_mask] = open_legs[i]

        new_closed_legs_mask = np.where(copylegs>0)[0]
        unique_closed_legs = np.unique(copylegs[new_closed_legs_mask])
        new_closed_legs = np.arange(1, unique_closed_legs.size+1)

        for i, unique_leg_i in enumerate(unique_closed_legs):
            temp_mask =np.where(copylegs ==unique_leg_i)
            copylegs[temp_mask] = new_closed_legs[i]

        tracking = [0]
        new_environment_legs = []
        for i in copy_shape:
            tracking.append(tracking[-1]+i)

        # i.all() does not work properly, use not (i< 0).all() < 0 instead
        new_environment_legs = [i for i in np.array_split(copylegs, tracking) if len(i)>0 and not (i< 0).all()]
        full_tree, environment_tree = [], []

        # manual sorting
        for i in tensors_to_loop_over:
            full_tree.extend((i,i))
            if i.value == current_value:
                environment_tree.append(i)
            else:
                environment_tree.extend((i,i))

        current_network['entire_network'] = full_tree
        current_network['unique_tensors'] = tensors_to_loop_over
        current_network['environment'] = environment_tree
        current_network['environment_legs'] = new_environment_legs


def get_optimal_order(node, dict_of_networks, optimize_type):
    """ Docstring for get_optimal_orders() """
    copied_environment_legs = [np.copy(l) for l in
                               dict_of_networks['environment_legs']]
    list_of_tensors, new_path = [], []
    new_path_energy = []
    copied_energy_legs = np.copy(dict_of_networks['full_legs'])
    copied_energy_legs = [l.tolist() for l in copied_energy_legs]
    copied_copied_legs = [l.tolist() for l in copied_environment_legs]
    k = [m for n in copied_copied_legs for m in n]
    out = np.arange(0, np.abs(np.min(k)))[::-1]

    for legs in copied_environment_legs:
        legs += np.abs(np.min(k))

    if len(dict_of_networks['bond']) == 2:
        for m,n in zip(dict_of_networks['environment'],
                       copied_environment_legs[:-2]):
            new_path.append(m.current_tensor)
            new_path.append(n)
        new_path.append(np.eye(2))
        new_path.append(copied_environment_legs[-2])
        new_path.append(np.eye(2))
        new_path.append(copied_environment_legs[-1])

    elif len(dict_of_networks['bond']) == 1:
        for m,n in zip(dict_of_networks['environment'],
                       copied_environment_legs[:-1]):
            new_path.append(m.current_tensor)
            new_path.append(n)
        new_path.append(np.eye(2))
        new_path.append(copied_environment_legs[-1])

    new_opt_path = oe.contract_path(*new_path, out, optimize=optimize_type)
    # print(copied_energy_legs)

    if len(dict_of_networks['bond']) == 2:
        for m,n in zip(dict_of_networks['entire_network'], copied_energy_legs[:-2]):
            new_path_energy.append(m.current_tensor)
            new_path_energy.append(n)
        # print(copied_energy_legs[:-2])
        # print([k.value for k in dict_of_networks['entire_network']])
        new_path_energy.append(np.eye(2))
        new_path_energy.append(copied_energy_legs[-2])
        new_path_energy.append(np.eye(2))
        new_path_energy.append(copied_energy_legs[-1])
    elif len(dict_of_networks['bond']) == 1:
        for m,n in zip(dict_of_networks['entire_network'], copied_energy_legs[:-1]):
            new_path_energy.append(m.current_tensor)
            new_path_energy.append(n)

        new_path_energy.append(np.eye(2))
        new_path_energy.append(copied_energy_legs[-1])

    new_opt_path_energy = oe.contract_path(*new_path_energy,optimize=optimize_type)
    # add new keys to existing dictionary
    dict_of_networks['einsum_path'] = new_opt_path[0]
    dict_of_networks['einsum_indices'] = copied_environment_legs
    dict_of_networks['out_list'] = out
    dict_of_networks['tensor_list'] = list_of_tensors
    dict_of_networks['einsum_energy_indices'] = copied_energy_legs
    dict_of_networks['einsum_path_energy'] = new_opt_path_energy[0]


def contract_network(operators, network, contract_type='env'):
    temp_operators = [i for i in operators[0]]
    path = []
    if contract_type == 'env':
        for m,n in zip(network['environment'], network['einsum_indices']):
            path.append(m.current_tensor)
            path.append(n)
        for m,n in zip(temp_operators, network['einsum_indices'][-len(temp_operators):]):
            path.append(m)
            path.append(n)

        return oe.contract(*path, network['out_list'],
                    optimize=network['einsum_path'])

    elif contract_type == 'energy':
        for m,n in zip(network['entire_network'], network['einsum_energy_indices']):
            path.append(m.current_tensor)
            # print(m.current_tensor)
            path.append(n)

        for m,n in zip(temp_operators, network['einsum_energy_indices'][-len(temp_operators):]):
            path.append(m)
            path.append(n)
            # to_contract = [*[m.cur_tensor, n] in zip(network['entire_network'], network['full_legs'])]
        # print(oe.contract(*path, optimize=network['einsum_path_energy']))
        return oe.contract(*path, optimize=network['einsum_path_energy'])


def get_energy(tree_object, node):
    """ Docstring for get_energy() """
    temp = 0
    if tree_object.backend == 'torch':
        for operators in tree_object.hamiltonian:
            if operators[1] > 0:
                for network in node.vertical_networks:
                    if np.allclose(operators[1], network['bondspace']):
                        temp += (contract_network(operators, network,
                                contract_type='energy')*operators[-1][0]).item()
                for network in node.horizontal_networks:
                    if np.allclose(operators[1], network['bondspace']):


                        temp += (contract_network(operators, network,
                                contract_type='energy')*operators[-1][1]).item()

            else:
                for network in node.one_site_networks:
                    if np.allclose(operators[1], network['bondspace']):

                        temp += (contract_network(operators, network,
                                contract_type='energy')*operators[-1][0]).item()

    elif tree_object.backend == 'numpy':
        for operators in tree_object.hamiltonian:

            if operators[1] > 0:
                for network in node.vertical_networks:
                    if np.allclose(operators[1], network['bondspace']):
                        # print('ver ',contract_network(operators, network,
                        # contract_type='energy').size())
                        temp += contract_network(operators, network,
                                contract_type='energy')*operators[-1][0]

                for network in node.horizontal_networks:
                    if np.allclose(operators[1], network['bondspace']):

                        # print('hor ',contract_network(operators, network,
                        # contract_type='energy').size())
                        temp += contract_network(operators, network,
                                contract_type='energy')*operators[-1][1]
            else:
                for network in node.one_site_networks:
                    if np.allclose(operators[1], network['bondspace']):

                        # print('one', contract_network(operators, network,
                        # contract_type='energy').size())
                        temp += contract_network(operators, network,
                                contract_type='energy')*operators[-1][0]

    return temp

@timer
def optimize_tensor(tree_object, node):
    """ VOID: optimize method for a single tensor in the Tree Tensor Network using optimal einsum"""

    if tree_object.backend == 'torch':
        node.cache_tensor.zero_()
        for operators in tree_object.hamiltonian:
            for network in node.vertical_networks:
                if np.allclose(operators[1], network['bondspace']):
                    node.cache_tensor.add_(contract_network(operators, network)*operators[-1][0])
            for network in node.horizontal_networks:
                if np.allclose(operators[1], network['bondspace']):
                    node.cache_tensor.add_(contract_network(operators, network)*operators[-1][1])

            for network in node.one_site_networks:
                if np.allclose(operators[1], network['bondspace']):
                    node.cache_tensor.add_(contract_network(operators, network)*operators[-1][0])

        new_shapes = node.cache_tensor.shape
        # need to transpose since torch saves n x n matrix of u, n being the first axes
        ut, s, v = node.cache_tensor.reshape(new_shapes[0], np.prod(new_shapes[1:])).T.svd(some=True)
        # torch returns u transposed hence ut.T
        node.current_tensor = -1.*torch.matmul(v,ut.T).reshape(new_shapes)

    elif tree_object.backend == 'numpy':

        node.cache_tensor.fill(0)
        for operators in tree_object.hamiltonian:

            if operators[1] > 0:

                for network in node.vertical_networks:
                    # print(network['bondspace'],operators[1])
                    if np.allclose(operators[1], network['bondspace']):
                        node.cache_tensor+=contract_network(operators, network)*operators[-1][0]

                for network in node.horizontal_networks:
                    if np.allclose(operators[1], network['bondspace']):
                        node.cache_tensor+=contract_network(operators, network)*operators[-1][1]
            else:
                for network in node.one_site_networks:
                    if np.allclose(operators[1], network['bondspace']):
                        node.cache_tensor+=contract_network(operators, network)*operators[-1][0]

        new_shapes = node.cache_tensor.shape
        u, s, v = np.linalg.svd(node.cache_tensor.reshape(new_shapes[0],
            np.prod(new_shapes[1:])).T, full_matrices = False)

        node.current_tensor =-1.*np.dot(v.T, u.T).reshape(new_shapes)

    for a_node in tree_object.node_list:
        if a_node.value == node.value:
            a_node.current_tensor = node.current_tensor


def exact_energy(N, hamiltonian, dimension):
    h = 0.0000
    if dimension == '2D' or dimension == '2d' or dimension == 2:
        print('computing 2D hamiltonian')
        L = int(N**0.5)
        for i in hamiltonian:
            if len(i[0]) == 1: # if length of operator list is 1
                operator = spl.csr_matrix(i[0][0])
                for k in range(N):
                    h += spl.kron(spl.kron(spl.identity(2**k), operator, 'csr'),
                        spl.identity(2**(N-k-1)), 'csr')*i[-1][0]
            if len(i[0]) == 2: # if length of operator list is 2
                if type(i[1]) == int:
                    operators = [spl.csr_matrix(j) for j in i[0]]

                    spacing_identity = spl.identity(2**(i[1]-1))
                    operators_2_site = spl.kron(spl.kron(operators[0], spacing_identity, 'csr'),
                        operators[1], 'csr')
                    # J+J- on i,i+1 and J-J+ on i-1,i
                    operators_2_site_reversed = spl.kron(spl.kron(operators[1], spacing_identity, 'csr'),
                        operators[0], 'csr')
                    # horizontal terms
                    for k in range(N):
                        if k%L:
                            h += spl.kron(spl.kron(spl.identity(2**(k-1)),operators_2_site, 'csr'),
                                spl.identity(2**(N-k-i[1])), 'csr')*i[2][0]
                    # vertical terms
                    for k in range(N-L):
                        h += spl.kron(spl.kron(spl.kron(spl.kron(spl.identity(2**k),operators[0], 'csr'),
                            spl.identity(2**(L-1)), 'csr'), operators[1], 'csr'), spl.identity(2**(N-L-k-1)),'csr')*i[2][1]


                    # boundary terms
                    for k in range(L):
                        h += i[2][1]*spl.kron(spl.kron(spl.kron(spl.kron(spl.identity(2**k),
                            operators[0], 'csr'),spl.identity(2**(N-L-1)), 'csr'),
                            operators[1], 'csr'), spl.identity(2**(L-k-1)), 'csr')

                        h += i[2][0]*(spl.kron(spl.kron(spl.kron(spl.kron(spl.identity(2**(k*L)),
                            operators[0], 'csr'), spl.identity(2**(L-2)), 'csr'), operators[1], 'csr'),
                            spl.identity(2**(L*(L-k-1))), 'csr'))

                if type(i[1]) == float:
                    if i[1] == 1.5:
                        # upwards -> *i[2][1], downwards *i[2][0]
                        operators = [spl.csr_matrix(j) for j in i[0]]
                        for k in range(N-L):
                            if k%L:
                                # downward to the right
                                left_id, mid_id, right_id = k-1, L, N-L-(k-1)-2
                                # print(left_id, mid_id, right_id, left_id+mid_id+right_id)
                                h+=spl.kron(spl.kron(spl.kron(spl.kron(spl.identity(2**left_id), operators[0], 'csr'), spl.identity(2**mid_id), 'csr'),
                                    operators[1], 'csr'), spl.identity(2**right_id),'csr')*i[2][0]

                                # upward to the right
                                left_id_up, mid_id_up, right_id_up = k, L-2, N-(L-2)-k-2
                                # print(left_id_up, 1, mid_id_up, 1, right_id_up)
                                h+=spl.kron(spl.kron(spl.kron(spl.kron(spl.identity(2**left_id_up), operators[1], 'csr'), spl.identity(2**mid_id_up), 'csr'),
                                    operators[0], 'csr'), spl.identity(2**right_id_up),'csr')*i[2][1]
                        # boundaries right up, followed by right down:
                        for k in range(L-1):
                            # up
                            left_id, mid_id = L*k, 2*L-2
                            right_id = N - left_id - mid_id-2
                            # print(left_id, mid_id, right_id, left_id+mid_id+right_id)
                            h+=spl.kron(spl.kron(spl.kron(spl.kron(spl.identity(2**left_id), operators[1], 'csr'), spl.identity(2**mid_id), 'csr'),
                                operators[0], 'csr'), spl.identity(2**right_id),'csr')*i[2][1]

                            # down
                            left_id_down, mid_id_down = L*(k+1)-1, 0
                            right_id_down = N-left_id_down-mid_id_down - 2
                            # print(left_id_down, mid_id_down, right_id_down)
                            h+=spl.kron(spl.kron(spl.kron(spl.kron(spl.identity(2**left_id_down), operators[0], 'csr'), spl.identity(2**mid_id_down), 'csr'),
                                operators[1], 'csr'), spl.identity(2**right_id_down),'csr')*i[2][0]

                        # boundaries, followed by up right:
                        # for up left the first boundary is omitted and calculated under
                        # boundary top right upwards (to bottem):

                        for k in range(L-1):
                            # boundary top right upwards (to bottem):
                            left_id = k
                            mid_id = L*(L-1)
                            right_id = N - 2 - mid_id - left_id
                            # print(left_id, mid_id, right_id)
                            h+=spl.kron(spl.kron(spl.kron(spl.kron(spl.identity(2**left_id), operators[0], 'csr'), spl.identity(2**mid_id), 'csr'),
                                operators[1], 'csr'), spl.identity(2**right_id),'csr')*i[2][1]

                            left_id2 = k+1
                            mid_id2 = L*(L-1) - 2
                            right_id2 = N - 2 -left_id2 - mid_id2
                            # print(left_id2, mid_id2, right_id2)
                            # boundary bottem right downwards to top
                            # order of operators is correct (trust me)
                            h+=spl.kron(spl.kron(spl.kron(spl.kron(spl.identity(2**left_id2), operators[1], 'csr'), spl.identity(2**mid_id2), 'csr'),
                                operators[0], 'csr'), spl.identity(2**right_id2),'csr')*i[2][0]

                        # boundary top right [op1] to bottem left [op2] so upwards to the right:
                        h += spl.kron(spl.kron(spl.kron(spl.kron(spl.identity(2**(L-1)), operators[0], 'csr'), spl.identity(2**((L-2)*L)), 'csr'),
                            operators[1], 'csr'), spl.identity(2**(L-1)),'csr')*i[2][1]
                        # boundary bottem right [op1] to top left [op2] so downwards to the right:
                        h += spl.kron(spl.kron(spl.kron(spl.kron(spl.identity(2**(0)), operators[1], 'csr'), spl.identity(2**(N-2)), 'csr'),
                            operators[0], 'csr'), spl.identity(2**(0)),'csr')*i[2][0]


        return h


def rho_bot_sites(tree_object, sites, operators=None):
    """

    Args:
        tree_object (class): object from which to calculate reduced-density
                             matrix.
        sites (python list): sites of tree_object.root.lattice to use
                             example: [1,2,3,4]
        operators (list):    default None, can contain list op torch.cuda or np.ndarray
                             tensors depending on tree_object.backend
    Returns:
        if operators=None:   torch.cuda tensor or np.ndarray
        if operators!=None:  float32 or float64

    """
    temporary_network = []
    site_legs = np.arange(1,len(sites)*2+1)*-1
    site_bra_legs = site_legs[:int(site_legs.size/2)].astype(int).tolist()
    site_ket_legs = site_legs[int(site_legs.size/2):].astype(int).tolist()
    for tensor in tree_object.node_list:
        for site in sites:
            if site in tensor.lattice:
                temporary_network.append(tensor)

    unique_network = []
    for i in temporary_network:
        if i not in unique_network:
            unique_network.append(i)
        else:
            continue

    new_open_legs = np.arange(1, 2*(len(sites))+1)*-1
    new_bra_open_legs, new_ket_open_legs = np.array_split(new_open_legs, 2)
    new_bra_open_legs, new_ket_open_legs = list(reversed(new_bra_open_legs.tolist())), list(reversed(new_ket_open_legs.tolist()))
    all_legs = []

    for current_node in unique_network:
        if current_node.isRoot():

            current_node.bralegs = np.array([1,2,3])
            current_node.ketlegs = np.array([1, None, None])

            if current_node.left in unique_network and not current_node.right in unique_network:
                current_node.ketlegs[2] = current_node.bralegs[2]
            elif current_node.right in unique_network and not current_node.left in unique_network:
                current_node.ketlegs[1] = current_node.bralegs[1]

            mask_legs = np.where(current_node.ketlegs == None)[0]
            new_values = np.arange(np.max(current_node.bralegs)+1,
                np.max(current_node.bralegs)+mask_legs.size+1)
            current_node.ketlegs[mask_legs] = new_values
            max_leg = np.max(np.array([np.max(current_node.ketlegs), np.max(current_node.bralegs)]))

        if not current_node.isRoot():
            current_node.bralegs = [None]*len(current_node.current_tensor.shape)
            current_node.ketlegs = [None]*len(current_node.current_tensor.shape)
            current_node.bralegs, current_node.ketlegs = np.array(current_node.bralegs), np.array(current_node.ketlegs)

            if current_node.isLeftChild():
                current_node.bralegs[0] = current_node.parent.bralegs[1]
                current_node.ketlegs[0] = current_node.parent.ketlegs[1]

            if current_node.isRightChild():
                current_node.bralegs[0] = current_node.parent.bralegs[2]
                current_node.ketlegs[0] = current_node.parent.ketlegs[2]

            if current_node.layer != tree_object.cut:
                mask_legs = np.where(current_node.bralegs == None)[0]
                new_bralegs = np.arange(max_leg+1, max_leg+mask_legs.size+1)
                current_node.bralegs[mask_legs] = new_bralegs
                max_leg = np.max(current_node.bralegs)

            # for lower legs
            if current_node.left in unique_network and current_node.right in unique_network:
                mask_legs = np.where(current_node.ketlegs == None)[0]
                current_node.ketlegs[mask_legs] = np.arange(max_leg+1, max_leg+mask_legs.size+1)
                max_leg = np.max(current_node.ketlegs)

            elif current_node.left in unique_network and not current_node.right in unique_network:
                current_node.ketlegs[2] = current_node.bralegs[2]
                current_node.ketlegs[1] = max_leg+1
                max_leg = np.max(current_node.ketlegs)

            elif current_node.right in unique_network and not current_node.left in unique_network:
                current_node.ketlegs[1] = current_node.bralegs[1]
                current_node.ketlegs[2] = max_leg+1
                max_leg = np.max(current_node.ketlegs)

            # if current_node = bottem tensor
            elif not current_node.left in unique_network and not current_node.right in unique_network:
                # below is from new_methods
                for site, new_bra_leg, new_ket_leg in zip(sites, site_bra_legs, site_ket_legs):
                    # added flatten() like in old code:
                    if site in current_node.lattice.flatten():
                        index_to_mask = np.where(current_node.lattice.flatten() == site)[0]+1
                        current_node.bralegs[index_to_mask] = new_bra_leg
                        current_node.ketlegs[index_to_mask] = new_ket_leg

                for i_leg, b_leg in enumerate(current_node.ketlegs):
                    if b_leg is None:
                        current_node.ketlegs[i_leg] = max_leg+1
                        current_node.bralegs[i_leg] = max_leg+1
                        max_leg+=1

        all_legs.extend((current_node.bralegs, current_node.ketlegs))

    reduced_density_matrix_list = []
    order_legs = [i for i in range(1, max_leg+1)][::-1]
    for i in unique_network:
        reduced_density_matrix_list.extend((i,i))
    new_shape = 2**int(new_open_legs.size/2)

    all_legs_2 = [np.copy(l) for l in all_legs]
    tensor_list = []
    f = [l.tolist() for l in all_legs_2]
    k = [m for n in f for m in n]

    out = np.arange(0, np.abs(np.min(k)))[::-1]
    for s2 in all_legs_2:
        s2+= np.abs(np.min(k))
    new_path = []

    for m,n in zip(reduced_density_matrix_list, all_legs_2):
        new_path.append(m.current_tensor)
        new_path.append(n)
    if operators is not None:
        temp_op_legs = []
        for i in range(int(len(out)/2)):
            temp_op_legs.append([out[i], out[i+int(len(out)/2)]])
        for m,n in zip(operators, temp_op_legs):
            new_path.append(m)
            new_path.append(n)
        return oe.contract(*new_path), None
    # og_reduced_density_matrix = oe.contract(*new_path, out, optimize='greedy').item()
    # reduced_density_matrix = og_reduced_density_matrix.reshape(new_shape, new_shape) optimize='greedy'
    torch.cuda.empty_cache()
    return oe.contract(*new_path, out), None

def get_effective_ham_top(tree_object, layer):
    temporary_network = []
    site_legs = np.arange(1,len(sites)*2+1)*-1
    site_bra_legs = site_legs[:int(site_legs.size/2)].astype(int).tolist()
    site_ket_legs = site_legs[int(site_legs.size/2):].astype(int).tolist()
    for tensor in tree_object.node_list:
        for site in sites:
            if site in tensor.lattice:
                temporary_network.append(tensor)

    unique_network = []
    for i in temporary_network:
        if i not in unique_network:
            unique_network.append(i)
        else:
            continue

    new_open_legs = np.arange(1, 2*(len(sites))+1)*-1
    new_bra_open_legs, new_ket_open_legs = np.array_split(new_open_legs, 2)
    new_bra_open_legs, new_ket_open_legs = list(reversed(new_bra_open_legs.tolist())), list(reversed(new_ket_open_legs.tolist()))
    all_legs = []

    for current_node in unique_network:
        if current_node.isRoot():

            current_node.bralegs = np.array([1,2,3])
            current_node.ketlegs = np.array([1, None, None])

            if current_node.left in unique_network and not current_node.right in unique_network:
                current_node.ketlegs[2] = current_node.bralegs[2]
            elif current_node.right in unique_network and not current_node.left in unique_network:
                current_node.ketlegs[1] = current_node.bralegs[1]

            mask_legs = np.where(current_node.ketlegs == None)[0]
            new_values = np.arange(np.max(current_node.bralegs)+1,
                np.max(current_node.bralegs)+mask_legs.size+1)
            current_node.ketlegs[mask_legs] = new_values
            max_leg = np.max(np.array([np.max(current_node.ketlegs), np.max(current_node.bralegs)]))

        if not current_node.isRoot():
            current_node.bralegs = [None]*len(current_node.current_tensor.shape)
            current_node.ketlegs = [None]*len(current_node.current_tensor.shape)
            current_node.bralegs, current_node.ketlegs = np.array(current_node.bralegs), np.array(current_node.ketlegs)

            if current_node.isLeftChild():
                current_node.bralegs[0] = current_node.parent.bralegs[1]
                current_node.ketlegs[0] = current_node.parent.ketlegs[1]

            if current_node.isRightChild():
                current_node.bralegs[0] = current_node.parent.bralegs[2]
                current_node.ketlegs[0] = current_node.parent.ketlegs[2]

            if current_node.layer != tree_object.cut:
                mask_legs = np.where(current_node.bralegs == None)[0]
                new_bralegs = np.arange(max_leg+1, max_leg+mask_legs.size+1)
                current_node.bralegs[mask_legs] = new_bralegs
                max_leg = np.max(current_node.bralegs)

            # for lower legs
            if current_node.left in unique_network and current_node.right in unique_network:
                mask_legs = np.where(current_node.ketlegs == None)[0]
                current_node.ketlegs[mask_legs] = np.arange(max_leg+1, max_leg+mask_legs.size+1)
                max_leg = np.max(current_node.ketlegs)

            elif current_node.left in unique_network and not current_node.right in unique_network:
                current_node.ketlegs[2] = current_node.bralegs[2]
                current_node.ketlegs[1] = max_leg+1
                max_leg = np.max(current_node.ketlegs)

            elif current_node.right in unique_network and not current_node.left in unique_network:
                current_node.ketlegs[1] = current_node.bralegs[1]
                current_node.ketlegs[2] = max_leg+1
                max_leg = np.max(current_node.ketlegs)

            # if current_node = bottem tensor
            elif not current_node.left in unique_network and not current_node.right in unique_network:
                # below is from new_methods
                for site, new_bra_leg, new_ket_leg in zip(sites, site_bra_legs, site_ket_legs):
                    # added flatten() like in old code:
                    if site in current_node.lattice.flatten():
                        index_to_mask = np.where(current_node.lattice.flatten() == site)[0]+1
                        current_node.bralegs[index_to_mask] = new_bra_leg
                        current_node.ketlegs[index_to_mask] = new_ket_leg

                for i_leg, b_leg in enumerate(current_node.ketlegs):
                    if b_leg is None:
                        current_node.ketlegs[i_leg] = max_leg+1
                        current_node.bralegs[i_leg] = max_leg+1
                        max_leg+=1

        all_legs.extend((current_node.bralegs, current_node.ketlegs))

    reduced_density_matrix_list = []
    order_legs = [i for i in range(1, max_leg+1)][::-1]
    for i in unique_network:
        reduced_density_matrix_list.extend((i,i))
    new_shape = 2**int(new_open_legs.size/2)

    all_legs_2 = [np.copy(l) for l in all_legs]
    tensor_list = []
    f = [l.tolist() for l in all_legs_2]
    k = [m for n in f for m in n]

    out = np.arange(0, np.abs(np.min(k)))[::-1]
    for s2 in all_legs_2:
        s2+= np.abs(np.min(k))
    new_path = []

    for m,n in zip(reduced_density_matrix_list, all_legs_2):
        new_path.append(m.current_tensor)
        new_path.append(n)
    if operators is not None:
        temp_op_legs = []
        for i in range(int(len(out)/2)):
            temp_op_legs.append([out[i], out[i+int(len(out)/2)]])
        for m,n in zip(operators, temp_op_legs):
            new_path.append(m)
            new_path.append(n)
        return oe.contract(*new_path), None
    # og_reduced_density_matrix = oe.contract(*new_path, out, optimize='greedy').item()
    # reduced_density_matrix = og_reduced_density_matrix.reshape(new_shape, new_shape) optimize='greedy'
    torch.cuda.empty_cache()
    return effective_ham

def vector_correlator(tree_object, operators, power):
    """ supplementary function for plaquette AND dimer correlators

    Args:
        tree_object (TreeTensorNetwork): tree to calculate operators expression for
        operators (list): containes torch.cuda tensors or np.ndarrays of shapes
                          (d,d) where d is local hilbert space dimension of a site in the
                          bottem node
        power (int): determines the order of the correlation function.
                     example: power = 1 -> 2-point correlator, power = 2 -> 4-point correlator
    Returns:
        operators_total_list (list): list of all operator product combinations
    """
    all_products = compute_correlation_product(operators, power=power)
    operators_total_list = []
    for i in all_products:
        temp_operators_list = [operator for sub_operators in i for operator in sub_operators]
        operators_total_list.append(temp_operators_list)

    return operators_total_list


def n_point_correlator(tree_object, operators, sites):
    """
    computes N-point correlation function for tree_objects, using rho_bot_sites

    Args:
    tree_object (TreeTensorNetwork): tree to calculate expectation value of
    operators (list): containes torch.cuda tensors or np.ndarrays of shapes
    (d,d) where d is local hilbert space dimension of a site in the
    bottem node
    sites (list): containing sites (int) to apply operators on
    Returns:
    correlation_value (float): rho_bot_sites(Args)

    """
    if tree_object.backend == 'torch':
        return rho_bot_sites(tree_object, sites, operators)[0].item()
    elif tree_object.backend == 'numpy':
        return rho_bot_sites(tree_object, sites, operators)[0]


def dimer_dimer_correlator(tree_object, operators, direction):
    reshaped_lattice = tree_object.root.lattice
    shapes = reshaped_lattice.shape
    # x direction
    half_l_x = int(shapes[0]/2)
    half_l_y = int(shapes[1]/2)
    all_dimer_dimer_correlation_value = []
    all_two_point_correlation_value_0 = []
    all_two_point_correlation_value_1 = []
    all_operators_list = vector_correlator(tree_object, operators, 2)
    if (direction == 'x') or (direction == 'X'):
        for i in range(shapes[0]):
            for j in range(shapes[1]):
                dimer_x_sites_0 =  [reshaped_lattice[i,j], reshaped_lattice[i,(j+1)%shapes[1]]]
                dimer_x_sites_1 =  [reshaped_lattice[i, (j+half_l_x)%shapes[0]], reshaped_lattice[i, (j+half_l_x+1)%shapes[0]]]
                temp_sites = [*dimer_x_sites_0, *dimer_x_sites_1]
                temp_dimer_correlation_value = []
                temp_two_point_correlation_value_0 = []
                temp_two_point_correlation_value_1 = []

                for k in all_operators_list:
                    temp_dimer_correlation_value.append(n_point_correlator(tree_object, k, temp_sites))
                all_dimer_dimer_correlation_value.append(np.sum(temp_dimer_correlation_value))

                for k in operators:
                    temp_two_point_correlation_value_0.append(n_point_correlator(tree_object, k, dimer_x_sites_0))
                    temp_two_point_correlation_value_1.append(n_point_correlator(tree_object, k, dimer_x_sites_1))

                all_two_point_correlation_value_0.append(np.sum(temp_two_point_correlation_value_0))
                all_two_point_correlation_value_1.append(np.sum(temp_two_point_correlation_value_1))

    elif (direction == 'y') or (direction == 'Y'):
        for i in range(shapes[0]):
            for j in range(shapes[1]):
                dimer_y_sites_0 = [reshaped_lattice[i, j] , reshaped_lattice[(i+1)%shapes[0],j]]
                dimer_y_sites_1 = [reshaped_lattice[(i+half_l_y)%shapes[1],j], reshaped_lattice[(i+1+half_l_y)%shapes[1], j]]
                temp_sites = [*dimer_y_sites_0, *dimer_y_sites_1]
                temp_dimer_correlation_value = []
                temp_two_point_correlation_value_0 = []
                temp_two_point_correlation_value_1 = []

                for k in all_operators_list:
                    temp_dimer_correlation_value.append(n_point_correlator(tree_object, k, temp_sites))
                all_dimer_dimer_correlation_value.append(np.sum(temp_dimer_correlation_value))

                for k in operators:
                    temp_two_point_correlation_value_0.append(n_point_correlator(tree_object, k, dimer_y_sites_0))
                    temp_two_point_correlation_value_1.append(n_point_correlator(tree_object, k, dimer_y_sites_1))
                all_two_point_correlation_value_0.append(np.sum(temp_two_point_correlation_value_0))
                all_two_point_correlation_value_1.append(np.sum(temp_two_point_correlation_value_1))

    return np.mean(all_dimer_dimer_correlation_value)/2, all_dimer_dimer_correlation_value, np.mean(all_two_point_correlation_value_0), np.mean(all_two_point_correlation_value_1)


def bond_correlator(tree_object, operators):
    all_operators_2 = vector_correlator(tree_object, operators, 1)
    temp_lat = tree_object.root.lattice
    irange, jrange = temp_lat.shape
    bonds_x, bonds_y = [], []
    for i in range(irange):
        for j in range(jrange):
            sites_x = [temp_lat[i,j], temp_lat[i,(j+1)%jrange]]
            sites_y = [temp_lat[i, j] , temp_lat[(i+1)%irange,j]]
            temp_x, temp_y = [], []
            for op in all_operators_2:
                temp_x.append(n_point_correlator(tree_object, op, sites_x))
                temp_y.append(n_point_correlator(tree_object, op, sites_y))
            bonds_x.append(np.sum(temp_x))
            bonds_y.append(np.sum(temp_y))

    return bonds_x, bonds_y


def plaquette_correlator(tree_object, operators, sites):
    """ single plaquette expectation value """
    all_operators_4 = vector_correlator(tree_object, operators, 2)
    all_operators_2 = vector_correlator(tree_object, operators, 1)

    plaquettes = []
    alpha, beta, gamma, delta = sites
    orders4 = [[alpha, beta, gamma, delta],[alpha, delta, beta, gamma], [alpha, gamma, beta, delta]]
    signs4 = [2,2,-2]
    orders2 = [[alpha, beta], [gamma, delta], [alpha, delta], [beta, gamma], [alpha, gamma], [beta, delta]]
    for operator in all_operators_4:
        for order, sign in zip(orders4, signs4):
            plaquettes.append(sign*n_point_correlator(tree_object, operator, order))
    for operator in all_operators_2:
        for order in orders2:
            plaquettes.append(.5*n_point_correlator(tree_object, operator, order))
    return np.sum(plaquettes)


def compute_correlation_product(operator_list, power):
    return list(it.product(operator_list, repeat=int(power)))


def plaquette_correlators(tree_object, start_operators):
    """ new version, in use """
    reshaped_lattice = tree_object.root.lattice
    shapes = reshaped_lattice.shape
    # x direction
    half_l_x = int(shapes[0]/2)
    half_l_y = int(shapes[1]/2)
    all_plaquettes = []
    for i in range(shapes[0]):
        for j in range(shapes[1]):
            a = reshaped_lattice[i, j]
            b = reshaped_lattice[i, (j+1)%shapes[1]]
            g = reshaped_lattice[(i+1)%shapes[0], (j+1)%shapes[1]]
            d = reshaped_lattice[(i+1)%shapes[0], j]
            temp_plaq = plaquette_correlator(tree_object, start_operators, [a, b, g, d]) + .125
            all_plaquettes.append(temp_plaq)

    return all_plaquettes


def plaquette_plaquette_correlator(tree_object, operators):
    all_operators_8 = vector_correlator(tree_object, operators, 4)
    all_operators_6 = vector_correlator(tree_object, operators, 3)

    all_operators_4 = vector_correlator(tree_object, operators, 2)
    all_operators_2 = vector_correlator(tree_object, operators, 1)
    reshaped_lattice = tree_object.root.lattice
    shapes = reshaped_lattice.shape
    # x direction
    half_l_x = int(shapes[0]/2)
    half_l_y = int(shapes[1]/2)
    # x-direction
    mean_squared_plaquettes_x = []
    mean_squared_plaquettes_y = []
    x_plaquettes = []
    y_plaquettes = []
    for i in range(shapes[0]):
        for j in range(shapes[1]):
            print('working on %s-%s'%(i,j))
            x_temp_plaquette, y_temp_plaquette = [], []
            i_0 = reshaped_lattice[i, j]
            j_0 = reshaped_lattice[i, (j+1)%shapes[1]]
            k_0 = reshaped_lattice[(i+1)%shapes[0], (j+1)%shapes[1]]
            l_0 = reshaped_lattice[(i+1)%shapes[0], j]
            m_x = reshaped_lattice[i, (j+half_l_x)%shapes[0]]
            n_x = reshaped_lattice[i, (j+half_l_x+1)%shapes[0]]
            o_x = reshaped_lattice[(i+1)%shapes[1], (j+half_l_x+1)%shapes[0]]
            p_x = reshaped_lattice[(i+1)%shapes[1], (j+half_l_x)%shapes[0]]
            m_y = reshaped_lattice[(i+half_l_y)%shapes[1], j]
            n_y = reshaped_lattice[(i+half_l_y)%shapes[1], (j+1)%shapes[0]]
            o_y = reshaped_lattice[(i+half_l_y+1)%shapes[1], (j+1)%shapes[0]]
            p_y = reshaped_lattice[(i+half_l_y+1)%shapes[1], j]
            indices_8_x = [[i_0,j_0,k_0,l_0,m_x,n_x,o_x,p_x], [i_0,j_0,k_0,l_0,m_x,p_x,n_x,o_x], [i_0,j_0,k_0,l_0,m_x,o_x,n_x,p_x], # correct
                           [i_0,l_0,j_0,k_0,m_x,n_x,o_x,p_x], [i_0,l_0,j_0,k_0,m_x,p_x,n_x,o_x], [i_0,l_0,j_0,k_0,m_x,o_x,n_x,p_x], #
                           [i_0,k_0,j_0,l_0,m_x,n_x,o_x,p_x], [i_0,k_0,j_0,l_0,m_x,p_x,n_x,o_x], [i_0,k_0,j_0,l_0,m_x,o_x,n_x,p_x]]
            indices_6_x = [[i_0,j_0,k_0,l_0,m_x,n_x], [i_0,j_0,k_0,l_0,o_x,p_x], [i_0,j_0,k_0,l_0,m_x,p_x], [i_0,j_0,k_0,l_0,n_x,o_x],
                           [i_0,j_0,k_0,l_0,m_x,o_x], [i_0,j_0,k_0,l_0,n_x,p_x],
                           [i_0,l_0,j_0,k_0,m_x,n_x], [i_0,l_0,j_0,k_0,o_x,p_x], [i_0,l_0,j_0,k_0,m_x,p_x], [i_0,l_0,j_0,k_0,n_x,o_x],
                           [i_0,l_0,j_0,k_0,m_x,o_x], [i_0,l_0,j_0,k_0,n_x,p_x],
                           [i_0,k_0,j_0,l_0,m_x,n_x], [i_0,k_0,j_0,l_0,o_x,p_x], [i_0,k_0,j_0,l_0,m_x,p_x], [i_0,k_0,j_0,l_0,n_x,o_x],
                           [i_0,k_0,j_0,l_0,m_x,o_x], [i_0,k_0,j_0,l_0,n_x,p_x],
                           [i_0,j_0,m_x,n_x,o_x,p_x], [i_0,j_0,m_x,p_x,n_x,o_x], [i_0,j_0,m_x,o_x,n_x,p_x],
                           [k_0,l_0,m_x,n_x,o_x,p_x], [k_0,l_0,m_x,p_x,n_x,o_x], [k_0,l_0,m_x,o_x,n_x,p_x],
                           [i_0,l_0,m_x,n_x,o_x,p_x], [i_0,l_0,m_x,p_x,n_x,o_x], [i_0,l_0,m_x,o_x,n_x,p_x],
                           [j_0,k_0,m_x,n_x,o_x,p_x], [j_0,k_0,m_x,p_x,n_x,o_x], [j_0,k_0,m_x,o_x,n_x,p_x],
                           [i_0,k_0,m_x,n_x,o_x,p_x], [i_0,k_0,m_x,p_x,n_x,o_x], [i_0,k_0,m_x,o_x,n_x,p_x],
                           [j_0,l_0,m_x,n_x,o_x,p_x], [j_0,l_0,m_x,p_x,n_x,o_x], [j_0,l_0,m_x,o_x,n_x,p_x]]
            indices_4_x = [[i_0,j_0,k_0,l_0], [i_0,l_0,j_0,k_0], [i_0,k_0,j_0,l_0], [m_x,n_x,o_x,p_x], [m_x,p_x,n_x,o_x], [m_x,o_x,n_x,p_x],
                           [i_0,j_0,m_x,n_x], [i_0,j_0,n_x,o_x], [i_0,j_0,m_x,o_x], [i_0,j_0,n_x,p_x], [i_0,j_0,o_x,p_x], [i_0,j_0,m_x,p_x],
                           [k_0,l_0,m_x,n_x], [k_0,l_0,n_x,o_x], [k_0,l_0,m_x,o_x], [k_0,l_0,n_x,p_x], [k_0,l_0,o_x,p_x], [k_0,l_0,m_x,p_x],
                           [i_0,l_0,m_x,n_x], [i_0,l_0,n_x,o_x], [i_0,l_0,m_x,o_x], [i_0,l_0,n_x,p_x], [i_0,l_0,o_x,p_x], [i_0,l_0,m_x,p_x],
                           [j_0,k_0,m_x,n_x], [j_0,k_0,n_x,o_x], [j_0,k_0,m_x,o_x], [j_0,k_0,n_x,p_x], [j_0,k_0,o_x,p_x], [j_0,k_0,m_x,p_x],
                           [i_0,k_0,m_x,n_x], [i_0,k_0,n_x,o_x], [i_0,k_0,m_x,o_x], [i_0,k_0,n_x,p_x], [i_0,k_0,o_x,p_x], [i_0,k_0,m_x,p_x],
                           [j_0,l_0,m_x,n_x], [j_0,l_0,n_x,o_x], [j_0,l_0,m_x,o_x], [j_0,l_0,n_x,p_x], [j_0,l_0,o_x,p_x], [j_0,l_0,m_x,p_x]]
            indices_2_x = [[i_0,j_0], [k_0,l_0], [i_0,l_0], [j_0,k_0], [i_0,k_0], [j_0,l_0], [m_x,n_x], [o_x,p_x], [m_x,p_x], [n_x,o_x], [m_x,o_x], [n_x, p_x]]
            indices_8_y = [[i_0,j_0,k_0,l_0,m_y,n_y,o_y,p_y], [i_0,j_0,k_0,l_0,m_y,p_y,n_y,o_y], [i_0,j_0,k_0,l_0,m_y,o_y,n_y,p_y],
                           [i_0,l_0,j_0,k_0,m_y,n_y,o_y,p_y], [i_0,l_0,j_0,k_0,m_y,p_y,n_y,o_y], [i_0,l_0,j_0,k_0,m_y,o_y,n_y,p_y],
                           [i_0,k_0,j_0,l_0,m_y,n_y,o_y,p_y], [i_0,k_0,j_0,l_0,m_y,p_y,n_y,o_y], [i_0,k_0,j_0,l_0,m_y,o_y,n_y,p_y]]
            indices_6_y = [[i_0,j_0,k_0,l_0,m_y,n_y], [i_0,j_0,k_0,l_0,o_y,p_y], [i_0,j_0,k_0,l_0,m_y,p_y], [i_0,j_0,k_0,l_0,n_y,o_y],
                           [i_0,j_0,k_0,l_0,m_y,o_y], [i_0,j_0,k_0,l_0,n_y,p_y],
                           [i_0,l_0,j_0,k_0,m_y,n_y], [i_0,l_0,j_0,k_0,o_y,p_y], [i_0,l_0,j_0,k_0,m_y,p_y], [i_0,l_0,j_0,k_0,n_y,o_y],
                           [i_0,l_0,j_0,k_0,m_y,o_y], [i_0,l_0,j_0,k_0,n_y,p_y],
                           [i_0,k_0,j_0,l_0,m_y,n_y], [i_0,k_0,j_0,l_0,o_y,p_y], [i_0,k_0,j_0,l_0,m_y,p_y], [i_0,k_0,j_0,l_0,n_y,o_y],
                           [i_0,k_0,j_0,l_0,m_y,o_y], [i_0,k_0,j_0,l_0,n_y,p_y],
                           [i_0,j_0,m_y,n_y,o_y,p_y], [i_0,j_0,m_y,p_y,n_y,o_y], [i_0,j_0,m_y,o_y,n_y,p_y],
                           [k_0,l_0,m_y,n_y,o_y,p_y], [k_0,l_0,m_y,p_y,n_y,o_y], [k_0,l_0,m_y,o_y,n_y,p_y],
                           [i_0,l_0,m_y,n_y,o_y,p_y], [i_0,l_0,m_y,p_y,n_y,o_y], [i_0,l_0,m_y,o_y,n_y,p_y],
                           [j_0,k_0,m_y,n_y,o_y,p_y], [j_0,k_0,m_y,p_y,n_y,o_y], [j_0,k_0,m_y,o_y,n_y,p_y],
                           [i_0,k_0,m_y,n_y,o_y,p_y], [i_0,k_0,m_y,p_y,n_y,o_y], [i_0,k_0,m_y,o_y,n_y,p_y],
                           [j_0,l_0,m_y,n_y,o_y,p_y], [j_0,l_0,m_y,p_y,n_y,o_y], [j_0,l_0,m_y,o_y,n_y,p_y]]
            indices_4_y = [[i_0,j_0,k_0,l_0], [i_0,l_0,j_0,k_0], [i_0,k_0,j_0,l_0], [m_y,n_y,o_y,p_y], [m_y,p_y,n_y,o_y], [m_y,o_y,n_y,p_y],
                           [i_0,j_0,m_y,n_y], [i_0,j_0,n_y,o_y], [i_0,j_0,m_y,o_y], [i_0,j_0,n_y,p_y], [i_0,j_0,o_y,p_y], [i_0,j_0,m_y,p_y],
                           [k_0,l_0,m_y,n_y], [k_0,l_0,n_y,o_y], [k_0,l_0,m_y,o_y], [k_0,l_0,n_y,p_y], [k_0,l_0,o_y,p_y], [k_0,l_0,m_y,p_y],
                           [i_0,l_0,m_y,n_y], [i_0,l_0,n_y,o_y], [i_0,l_0,m_y,o_y], [i_0,l_0,n_y,p_y], [i_0,l_0,o_y,p_y], [i_0,l_0,m_y,p_y],
                           [j_0,k_0,m_y,n_y], [j_0,k_0,n_y,o_y], [j_0,k_0,m_y,o_y], [j_0,k_0,n_y,p_y], [j_0,k_0,o_y,p_y], [j_0,k_0,m_y,p_y],
                           [i_0,k_0,m_y,n_y], [i_0,k_0,n_y,o_y], [i_0,k_0,m_y,o_y], [i_0,k_0,n_y,p_y], [i_0,k_0,o_y,p_y], [i_0,k_0,m_y,p_y],
                           [j_0,l_0,m_y,n_y], [j_0,l_0,n_y,o_y], [j_0,l_0,m_y,o_y], [j_0,l_0,n_y,p_y], [j_0,l_0,o_y,p_y], [j_0,l_0,m_y,p_y]]
            indices_2_y = [[i_0,j_0], [k_0,l_0], [i_0,l_0], [j_0,k_0], [i_0,k_0], [j_0,l_0], [m_y,n_y], [o_y,p_y], [m_y,p_y], [n_y,o_y], [m_y,o_y], [n_y, p_y]]
            factors_8 = [4,4,-4,4,4,-4,-4,-4,4]
            factors_6 = [1,1,1,1,1,1,1,1,1,1,1,1,-1,-1,-1,-1,-1,-1,1,1,-1,1,1,-1,1,1,-1,1,1,-1,1,1,-1,1,1,-1]
            factors_4 = [.5,.5,-.5,.5,.5,-.5,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25,.25]
            # forgot that .5*.25 = .125 instead of .5, omegalul
            factors_2 = [.125,.125,.125,.125,.125,.125,.125,.125,.125,.125,.125,.125]

            for k in all_operators_8:
                for index_8_x, index_8_y, factor_8 in zip(indices_8_x, indices_8_y, factors_8):
                    # print('working on: ', index_8_x)
                    x_temp_plaquette.append(factor_8*n_point_correlator(tree_object, k, index_8_x))
                    # print('working on: ', index_8_y)
                    y_temp_plaquette.append(factor_8*n_point_correlator(tree_object, k, index_8_y))
                    torch.cuda.empty_cache()
            for k in all_operators_6:
                for index_6_x, index_6_y, factor_6 in zip(indices_6_x, indices_6_y, factors_6):
                    # print('working on: ', index_6_x)
                    x_temp_plaquette.append(factor_6*n_point_correlator(tree_object, k, index_6_x))
                    # print('working on: ', index_6_y)
                    y_temp_plaquette.append(factor_6*n_point_correlator(tree_object, k, index_6_y))
                torch.cuda.empty_cache()
            for k in all_operators_4:
                for index_4_x, index_4_y, factor_4 in zip(indices_4_x, indices_4_y, factors_4):
                    # print('working on: ', index_4_x)
                    x_temp_plaquette.append(factor_4*n_point_correlator(tree_object, k, index_4_x))
                    # print('working on: ', index_4_y)
                    y_temp_plaquette.append(factor_4*n_point_correlator(tree_object, k, index_4_y))
                    torch.cuda.empty_cache()
            for k in all_operators_2:
                for index_2_x, index_2_y, factor_2 in zip(indices_2_x, indices_2_y, factors_2):
                    # print('working on: ', index_2_x)
                    x_temp_plaquette.append(factor_2*n_point_correlator(tree_object, k, index_2_x))
                    # print('working on: ', index_2_y)
                    y_temp_plaquette.append(factor_2*n_point_correlator(tree_object, k, index_2_y))
                    torch.cuda.empty_cache()

            x_plaquettes.append(np.sum(x_temp_plaquette))
            y_plaquettes.append(np.sum(y_temp_plaquette))
            mean_squared_plaquettes_x.append(plaquette_correlator(tree_object, operators, [i_0, j_0, k_0, l_0])*plaquette_correlator(tree_object, operators, [m_x, n_x, o_x, p_x]))
            mean_squared_plaquettes_y.append(plaquette_correlator(tree_object, operators, [i_0, j_0, k_0, l_0])*plaquette_correlator(tree_object, operators, [m_y, n_y, o_y, p_y]))

            torch.cuda.empty_cache()
        torch.cuda.empty_cache()

    x_plaquettes.append(.125**2)
    y_plaquettes.append(.125**2)
    mean_squared_plaquette = np.mean(plaquette_correlators(tree_object, operators))**2

    # commented out y_plaquettes
    return np.mean(x_plaquettes), np.mean(y_plaquettes), y_plaquettes, x_plaquettes, mean_squared_plaquette, mean_squared_plaquettes_x, mean_squared_plaquettes_y

# under construction
def mean_two_point_correlator_i_ir(tree_object, operators, correct_magnetization):

    square_size = np.sqrt(tree_object.root.lattice.flatten().size).astype(int)
    lattice = tree_object.root.lattice
    bound = int(square_size/2)
    tiled_lattice = np.tile(lattice, (3,3))
    tiled_lattices = []

    # this is it:
    for x in range(square_size, 2*square_size):
        for y in range(square_size, 2*square_size):
            sub_tiled_lattice = tiled_lattice[x-bound:x+bound+1,y-bound:y+bound+1]
            tiled_lattices.append([tiled_lattice[x,y],sub_tiled_lattice])

    correlation_matrices = []
    for middle_point, sub_lattice in tiled_lattices:

        temp_correlation = np.zeros(sub_lattice.shape)
        # print(middle_point,sub_lattice)
        for x in range(square_size+1):
            for y in range(square_size+1):
                if middle_point != sub_lattice[x,y]:
                    temp_correlation[x,y] = n_point_correlator(tree_object,operators,
                        [middle_point, sub_lattice[x,y]])
                else:
                    temp_correlation[x,y]= 1.0 # correlation with itself is by def 1

        correlation_matrices.append(temp_correlation)
    # print(correlation_matrices)
    mean_correlation = np.mean(np.array(correlation_matrices), axis =0)
    magnetizations = []

    for x, y in list(it.combinations(lattice.flatten(),2)):
        magnetizations.append(n_point_correlator(tree_object, [operators[0]], [x])*
                              n_point_correlator(tree_object, [operators[0]], [y]))

    mean_magnetization = np.mean(magnetizations)
    if correct_magnetization:
        mean_correlation -= np.ones(mean_correlation.shape)*mean_magnetization
    return mean_correlation, mean_magnetization


def optimize_network(tree_object, probe_length, var_error, max_iterations, printf = False, exact = False):
    variance_error = 10
    counter = 0
    probed_energies = []
    if exact:
        loop_length = 1
    else:
        loop_length = tree_object.cut+1
    for j in range(probe_length):
        # begin 1 sweep
        temp = tree_object.root
        for i in range(loop_length): # works better than writing it out since we recursively take the .left of current node
            optimize_tensor(tree_object, temp)
            temp = temp.left
        # end one sweep
        probed_energies.append(get_energy(tree_object, tree_object.root))
    probed_energies = np.array(probed_energies, dtype = 'float64')
    while(variance_error > var_error):
        probed_energies = np.roll(probed_energies, -1)
        temp = tree_object.root
        for i in range(loop_length):
            optimize_tensor(tree_object, temp)
            temp = temp.left
        # end one sweep
        temp_energy = get_energy(tree_object, tree_object.root)
        probed_energies[-1] = temp_energy
        variance_error = np.var(probed_energies)

        tree_object.energy_per_sweep_list.append(temp_energy)
        delta_energy = np.abs(np.abs(probed_energies[-1])-np.abs(probed_energies[-2]))
        # print(probed_energies, get_energy_v2(tree_object, tree_object.root))
        if printf:
            print('var error:', variance_error,
            ' delta E:', np.abs(probed_energies[-1])-np.abs(probed_energies[-2]),
            ' energy: ',get_energy(tree_object, tree_object.root))
        counter += 1
        if max_iterations != None:
            if (counter > max_iterations) or (np.abs(delta_energy)<1e-15):
                print('ended with variance:', variance_error)
                tree_object.current_iteration = counter
                break

    print('converged up to variance of:%s at iteration %s'%(variance_error, counter))
    return
